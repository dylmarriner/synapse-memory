"""Agent federation — minimal multi-node P2P memory sync.

A first-cut, pull-based federation layer.  Each node periodically pulls
memories created on its configured peers since the last successful sync
and upserts them locally, keyed by the globally-unique memory ``id`` so
sync is idempotent and never duplicates.

Wire protocol (see ``app/routers/federation.py``):

    POST /v1/federation/hello  — peer discovery handshake
    GET  /v1/federation/pull   — serve memories created since ?since=ISO8601
    POST /v1/federation/push   — receive a memory batch from a peer

Auth: every request carries an ``X-Federation-Signature`` header — an
HMAC-SHA256 hex digest of the canonical payload using ``FEDERATION_SECRET``.
This keeps federation independent of the node's agent-facing NEXUS_SECRET,
so peers don't have to share their primary credential.

Conflict resolution: last-writer-wins.  An incoming memory replaces the
local copy only when it has a higher ``version``, or an equal version with
a strictly newer ``created_at``.  Embeddings are intentionally NOT synced
— each node regenerates them locally via its own embedding model so nodes
with differing ``EMBEDDING_DIMS`` stay compatible.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal

log = logging.getLogger("nexus.federation")

# Per-peer cursor: ISO8601 timestamp of the newest memory we've pulled.
# In-memory only — on restart we re-pull from the beginning, which is safe
# because upserts are idempotent by id.
_peer_cursors: dict[str, str] = {}

# Fields carried across the wire.  Deliberately excludes ``embedding``.
_SYNC_FIELDS = (
    "id", "agent_name", "content", "memory_type", "importance",
    "confidence", "version", "confirmed_count", "contradicted_count",
    "created_at", "valid_from", "valid_until", "metadata",
)


def node_id() -> str:
    if settings.federation_node_id:
        return settings.federation_node_id
    import socket
    return socket.gethostname()


# ── HMAC signing ──────────────────────────────────────────────────────────

def sign(payload: str) -> str:
    """Return the hex HMAC-SHA256 of ``payload`` keyed by the shared secret."""
    return hmac.new(
        settings.federation_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify(payload: str, signature: str) -> bool:
    if not settings.federation_secret or not signature:
        return False
    return hmac.compare_digest(sign(payload), signature)


# ── Serialization ─────────────────────────────────────────────────────────

def _iso(v) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else (v or None)


async def pull_memories(since: str | None, limit: int) -> list[dict]:
    """Return memories created strictly after ``since`` (oldest first).

    Joins agent name so the receiver can map to (or create) its own agent
    row without sharing internal UUIDs.
    """
    where = "WHERE m.superseded_by IS NULL"
    params: dict = {"limit": limit}
    if since:
        where += " AND m.created_at > CAST(:since AS timestamptz)"
        params["since"] = since
    rows = (await _fetch(f"""
        SELECT m.id, a.name AS agent_name, m.content, m.memory_type,
               m.importance, m.confidence, m.version,
               m.confirmed_count, m.contradicted_count,
               m.created_at, m.valid_from, m.valid_until, m.metadata
        FROM memories m
        LEFT JOIN agents a ON a.id = m.agent_id
        {where}
        ORDER BY m.created_at ASC
        LIMIT :limit
    """, params))
    out = []
    for r in rows:
        d = dict(r._mapping)
        d["id"] = str(d["id"])
        d["created_at"] = _iso(d["created_at"])
        d["valid_from"] = _iso(d["valid_from"])
        d["valid_until"] = _iso(d["valid_until"])
        out.append(d)
    return out


async def _fetch(sql: str, params: dict):
    async with SessionLocal() as db:
        return (await db.execute(text(sql), params)).fetchall()


async def apply_batch(memories: list[dict]) -> dict:
    """Upsert a batch of peer memories, last-writer-wins by (version, created_at).

    Returns counts of inserted / updated / skipped rows.
    """
    inserted = updated = skipped = 0
    inserted_rows: list[dict] = []
    async with SessionLocal() as db:
        for m in memories:
            mid = m.get("id")
            if not mid or not m.get("content"):
                skipped += 1
                continue

            # Resolve / create the agent row by name.
            agent_id = None
            name = m.get("agent_name")
            if name:
                row = (await db.execute(text(
                    "SELECT id FROM agents WHERE name = :n LIMIT 1"
                ), {"n": name})).fetchone()
                if row:
                    agent_id = row.id
                else:
                    row = (await db.execute(text(
                        "INSERT INTO agents (name) VALUES (:n) RETURNING id"
                    ), {"n": name})).fetchone()
                    agent_id = row.id

            existing = (await db.execute(text(
                "SELECT version, created_at FROM memories WHERE id = :id"
            ), {"id": mid})).fetchone()

            vals = {
                "id": mid,
                "agent_id": agent_id,
                "content": m["content"],
                "memory_type": m.get("memory_type") or "observation",
                "importance": float(m.get("importance") or 0.5),
                "confidence": float(m.get("confidence") or 1.0),
                "version": int(m.get("version") or 1),
                "confirmed_count": int(m.get("confirmed_count") or 0),
                "contradicted_count": int(m.get("contradicted_count") or 0),
                "created_at": m.get("created_at"),
                "valid_from": m.get("valid_from"),
                "valid_until": m.get("valid_until"),
                "metadata": _json(m.get("metadata")),
            }

            if existing is None:
                await db.execute(text("""
                    INSERT INTO memories
                        (id, agent_id, content, memory_type, importance, confidence,
                         version, confirmed_count, contradicted_count, created_at,
                         valid_from, valid_until, metadata)
                    VALUES
                        (:id, :agent_id, :content, :memory_type, :importance, :confidence,
                         :version, :confirmed_count, :contradicted_count,
                         COALESCE(CAST(:created_at AS timestamptz), NOW()),
                         CAST(:valid_from AS timestamptz), CAST(:valid_until AS timestamptz),
                         CAST(:metadata AS jsonb))
                """), vals)
                inserted += 1
                inserted_rows.append(m)
            elif _wins(vals, existing):
                await db.execute(text("""
                    UPDATE memories SET
                        agent_id = :agent_id, content = :content, memory_type = :memory_type,
                        importance = :importance, confidence = :confidence, version = :version,
                        confirmed_count = :confirmed_count, contradicted_count = :contradicted_count,
                        valid_from = CAST(:valid_from AS timestamptz),
                        valid_until = CAST(:valid_until AS timestamptz),
                        metadata = CAST(:metadata AS jsonb)
                    WHERE id = :id
                """), vals)
                updated += 1
            else:
                skipped += 1
        await db.commit()

    # Newly-inserted rows have no embedding — queue them for the worker so
    # they become recall-able.  Best-effort.
    if inserted_rows:
        await _enqueue_embed(inserted_rows)
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _wins(incoming: dict, existing) -> bool:
    if incoming["version"] != existing.version:
        return incoming["version"] > existing.version
    inc = incoming.get("created_at")
    if not inc or existing.created_at is None:
        return False
    try:
        inc_dt = datetime.fromisoformat(inc) if isinstance(inc, str) else inc
    except ValueError:
        return False
    return inc_dt > existing.created_at


def _json(v) -> str:
    import json
    if v is None:
        return "{}"
    if isinstance(v, str):
        return v
    return json.dumps(v)


async def _enqueue_embed(rows: list[dict]) -> None:
    """Queue extraction jobs for freshly-inserted peer memories so the worker
    generates embeddings (and entities) locally — matching the job shape that
    app/memory/ingest.py pushes onto nexus:extract."""
    try:
        import json
        from app.redis_util import make_redis
        r = make_redis(decode_responses=True)
        for m in rows:
            job = {
                "memory_id": str(m["id"]),
                "agent_id": m.get("agent_name"),
                "content": m.get("content", ""),
                "importance": float(m.get("importance") or 0.5),
                "needs_embedding": True,
                # Peer already classified/extracted; just embed locally.
                "needs_classification": False,
            }
            await r.rpush("nexus:extract", json.dumps(job))
        await r.aclose()
    except Exception as e:
        log.debug("federation embed enqueue skipped: %s", e)


# ── Outbound pull loop ─────────────────────────────────────────────────────

async def _pull_from_peer(client: httpx.AsyncClient, peer: str) -> None:
    since = _peer_cursors.get(peer)
    params = {"limit": settings.federation_batch_size}
    if since:
        params["since"] = since
    canonical = f"pull:{since or ''}"
    resp = await client.get(
        f"{peer}/v1/federation/pull",
        params=params,
        headers={"X-Federation-Signature": sign(canonical)},
        timeout=20.0,
    )
    resp.raise_for_status()
    body = resp.json()
    memories = body.get("memories", [])
    if not memories:
        return
    stats = await apply_batch(memories)
    newest = max((m["created_at"] for m in memories if m.get("created_at")), default=since)
    if newest:
        _peer_cursors[peer] = newest
    log.info("federation pull %s: %s (cursor=%s)", peer, stats, newest)


async def federation_loop() -> None:
    """Background task: periodically pull from every configured peer."""
    if not settings.federation_enabled:
        return
    if not settings.federation_secret:
        log.warning("federation enabled but FEDERATION_SECRET is empty — disabled")
        return
    peers = settings.federation_peer_list
    log.info("federation loop started — node=%s peers=%s interval=%ds",
             node_id(), peers, settings.federation_interval_seconds)
    async with httpx.AsyncClient() as client:
        while True:
            for peer in settings.federation_peer_list:
                try:
                    await _pull_from_peer(client, peer)
                except Exception as e:
                    log.warning("federation pull from %s failed: %s", peer, e)
            await asyncio.sleep(settings.federation_interval_seconds)
