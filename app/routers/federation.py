"""Federation router — peer-to-peer memory sync endpoints.

These routes are authenticated by HMAC (``X-Federation-Signature``) rather
than the agent-facing Bearer secret, so the router is mounted WITHOUT the
global ``_verify_key`` dependency.  See ``app/federation.py`` for protocol.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app import federation as fed
from app.config import settings

log = logging.getLogger("nexus.federation")

router = APIRouter()


def _guard(canonical: str, signature: str | None) -> None:
    if not settings.federation_enabled:
        raise HTTPException(status_code=404, detail="Federation disabled")
    if not fed.verify(canonical, signature or ""):
        raise HTTPException(status_code=401, detail="Invalid federation signature")


class HelloRequest(BaseModel):
    node_id: str
    peer_url: str | None = None


@router.post("/hello")
async def hello(body: HelloRequest, request: Request):
    """Peer discovery handshake. Returns this node's identity and size."""
    sig = request.headers.get("X-Federation-Signature")
    _guard(f"hello:{body.node_id}", sig)
    rows = await fed._fetch(
        "SELECT COUNT(*) AS n FROM memories WHERE superseded_by IS NULL", {}
    )
    return {
        "node_id": fed.node_id(),
        "memory_count": int(rows[0].n) if rows else 0,
        "peers": settings.federation_peer_list,
        "version": "1.0.0",
    }


@router.get("/pull")
async def pull(
    request: Request,
    since: str | None = Query(None, description="ISO8601 — return memories created after this"),
    limit: int = Query(200, ge=1, le=2000),
):
    """Serve memories created after ``since`` (oldest first)."""
    sig = request.headers.get("X-Federation-Signature")
    _guard(f"pull:{since or ''}", sig)
    memories = await fed.pull_memories(since, limit)
    return {
        "node_id": fed.node_id(),
        "count": len(memories),
        "memories": memories,
    }


@router.post("/push")
async def push(request: Request):
    """Receive a memory batch from a peer and upsert it locally."""
    raw = await request.body()
    sig = request.headers.get("X-Federation-Signature")
    _guard(raw.decode("utf-8", "replace"), sig)
    import json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    memories = payload.get("memories", [])
    if not isinstance(memories, list):
        raise HTTPException(status_code=400, detail="'memories' must be a list")
    stats = await fed.apply_batch(memories)
    log.info("federation push received: %s", stats)
    return {"node_id": fed.node_id(), **stats}
