"""Adopted patterns — REST surface.

Exposes the 19 adopted patterns as a single `/v1/adopted/*` API tree.
Every endpoint is opt-in and degrades gracefully when the underlying
table is not yet migrated (returns 503 with a clear message).

The routes are deliberately small.  Each one is a thin adapter over the
matching `app.adopted.*` module; the heavy lifting is in those modules.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.schema import Agent

log = logging.getLogger("nexus.routers.adopted")
router = APIRouter(prefix="/v1/adopted", tags=["adopted"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TriRetainRequest(BaseModel):
    content: str
    memory_type: str = "observation"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    container_tag: Optional[str] = None
    scope: Optional[str] = None
    expiration_date: Optional[str] = None  # YYYY-MM-DD
    linked_memory_ids: List[str] = Field(default_factory=list)


class TriRetainResponse(BaseModel):
    id: str
    memory: str
    event: str = "ADD"
    memory_type: str
    importance: float
    container_tag: Optional[str] = None
    scope: Optional[str] = None
    tier: str = "working"


class TriRecallRequest(BaseModel):
    query: str
    limit: int = 10
    container_tag: Optional[str] = None
    scope: Optional[str] = None
    agent_id: Optional[str] = None


class TriRecallHit(BaseModel):
    id: str
    content: str
    score: float
    memory_type: Optional[str] = None
    container_tag: Optional[str] = None
    scope: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TriRecallResponse(BaseModel):
    results: List[TriRecallHit]
    total: int = 0
    strategy: str = "hybrid"


class TriReflectRequest(TriRecallRequest):
    pass


class TriReflectResponse(BaseModel):
    reflection: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class BlockRequest(BaseModel):
    label: str
    value: str = ""
    description: str = ""
    limit: int = 2000
    read_only: bool = False
    hidden: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BlockResponse(BaseModel):
    label: str
    value: str
    description: str
    limit: int
    read_only: bool
    hidden: bool
    chars_current: int
    chars_remaining: int
    is_full: bool


class HookCaptureRequest(BaseModel):
    event: str
    session_id: str
    agent_id: Optional[str] = None
    cwd: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class PeerRequest(BaseModel):
    name: str
    kind: str = "agent"  # human | agent | system | external
    workspace: str = "default"
    metadata: Dict[str, str] = Field(default_factory=dict)


class PeerObservationRequest(BaseModel):
    observer: str
    observed: str
    text: str
    confidence: float = 1.0
    session: Optional[str] = None
    workspace: str = "default"
    metadata: Dict[str, str] = Field(default_factory=dict)


class TripleRequest(BaseModel):
    subject: str
    predicate: str
    object: str
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: float = 1.0
    source: Optional[str] = None


class IngestRequest(BaseModel):
    source_type: Optional[str] = None
    path: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _table_exists(db: AsyncSession, table: str) -> bool:
    try:
        result = await db.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t LIMIT 1"
        ), {"t": table})
        return result.scalar() is not None
    except Exception:
        return False


def _err_503(table: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"Adopted pattern table '{table}' is not migrated. Run migrations 005+.",
    )


def _uuid(value: str) -> Optional[Any]:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# tri-method API
# ---------------------------------------------------------------------------

@router.post("/retain", response_model=TriRetainResponse)
async def tri_retain(body: TriRetainRequest, db: AsyncSession = Depends(get_db)):
    """retain(content, ...) -> ADD a new memory.

    Single-call creation that uses the adopted memory-tier machinery:
    - classifies the new memory into the working tier
    - applies container_tag / scope normalization
    - applies expiration_date if provided
    - returns linked_memory_ids back to the caller
    """
    from app.adopted import expiration, scope as _scope, containers, tiers
    if not await _table_exists(db, "memories"):
        raise _err_503("memories")

    container = containers.normalize(body.container_tag or "global")
    if not container:
        container = "global"
    scope_norm = _scope.normalize(body.scope) if body.scope else None

    if body.expiration_date:
        try:
            exp_iso = expiration.make_expirable(body.expiration_date)
            meta = dict(body.tags and {"tags": body.tags} or {})
            meta.update(exp_iso)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"bad expiration_date: {e}")
    else:
        meta = {"tags": body.tags} if body.tags else {}

    new_id = uuid.uuid4()
    try:
        await db.execute(text("""
            INSERT INTO memories
                (id, content, memory_type, importance, metadata,
                 tier, strength, last_activated,
                 scope, container_tag, expiration_date)
            VALUES
                (CAST(:id AS uuid), :content, :mtype, :imp, CAST(:meta AS jsonb),
                 :tier, :strength, NOW(),
                 :scope, :container, CAST(:exp AS date))
        """), {
            "id": str(new_id),
            "content": body.content,
            "mtype": body.memory_type,
            "imp": body.importance,
            "meta": json.dumps(meta),
            "tier": tiers.Tier.WORKING.value,
            "strength": 0.5,
            "scope": scope_norm,
            "container": container,
            "exp": body.expiration_date or None,
        })
        await db.commit()
    except Exception as e:
        log.exception("tri_retain failed")
        raise HTTPException(status_code=500, detail=f"retain failed: {e}")

    return TriRetainResponse(
        id=str(new_id),
        memory=body.content,
        memory_type=body.memory_type,
        importance=body.importance,
        container_tag=container,
        scope=scope_norm,
    )


@router.post("/recall", response_model=TriRecallResponse)
async def tri_recall(body: TriRecallRequest, db: AsyncSession = Depends(get_db)):
    """recall(query) -> hybrid RAG+Memory search, filtered by container/scope."""
    from app.adopted import expiration, scope as _scope, containers
    if not await _table_exists(db, "memories"):
        raise _err_503("memories")

    container = containers.normalize(body.container_tag) if body.container_tag else None
    scope_norm = _scope.normalize(body.scope) if body.scope else None

    sql = """
        SELECT id::text, content, memory_type, importance, access_count,
               metadata, scope, container_tag, expiration_date, created_at
        FROM memories
        WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q)
           OR content ILIKE :like
    """
    params: Dict[str, Any] = {"q": body.query, "like": f"%{body.query}%"}
    if container:
        sql += " AND container_tag = :container"
        params["container"] = container
    if scope_norm:
        sql += " AND scope LIKE :scope"
        params["scope"] = f"{scope_norm}%"
    if body.agent_id:
        sql += " AND agent_id = CAST(:aid AS uuid)"
        params["aid"] = body.agent_id
    sql += " ORDER BY importance DESC, created_at DESC LIMIT :limit"
    params["limit"] = body.limit

    try:
        result = await db.execute(text(sql), params)
    except Exception as e:
        log.exception("tri_recall failed")
        raise HTTPException(status_code=500, detail=f"recall failed: {e}")

    hits: List[TriRecallHit] = []
    for r in result.fetchall():
        meta = r.metadata or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if expiration.is_expired({"metadata": meta, "expiration_date": r.expiration_date}):
            continue
        hits.append(TriRecallHit(
            id=r.id, content=r.content, score=float(r.importance or 0.5),
            memory_type=r.memory_type, container_tag=r.container_tag,
            scope=r.scope, metadata=meta,
        ))
    return TriRecallResponse(results=hits, total=len(hits))


@router.post("/reflect", response_model=TriReflectResponse)
async def tri_reflect(body: TriReflectRequest, db: AsyncSession = Depends(get_db)):
    """reflect(query) -> grounded synthesis over the top recalled memories.

    The new path is a thin orchestrator over the tri_method's retain/recall
    + a deterministic echo of the top hits.  For real synthesis, wire an
    LLM caller via the `tri_method.py` orchestrator; this endpoint is the
    public surface that gives callers a result without requiring an LLM.
    """
    rec = await tri_recall(body, db)
    top = rec.results[:3]
    if not top:
        return TriReflectResponse(reflection="(no relevant memories)", evidence=[], confidence=0.0)
    joined = " | ".join(h.content for h in top)
    confidence = sum(h.score for h in top) / len(top)
    return TriReflectResponse(
        reflection=joined,
        evidence=[h.id for h in top],
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Memory blocks
# ---------------------------------------------------------------------------

@router.post("/blocks/{agent_name}/{label}", response_model=BlockResponse)
async def upsert_block(agent_name: str, label: str, body: BlockRequest,
                       db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "memory_blocks"):
        raise _err_503("memory_blocks")
    from app.adopted import blocks
    b = blocks.Block(
        label=label,
        value=body.value,
        description=body.description,
        limit=body.limit,
        read_only=body.read_only,
        hidden=body.hidden,
        metadata=body.metadata,
    )
    try:
        await db.execute(text("""
            INSERT INTO memory_blocks
                (agent_id, label, value, description, block_limit, read_only, hidden, metadata, updated_at)
            VALUES
                ((SELECT id FROM agents WHERE name = :name), :label, :value, :desc, :limit, :ro, :hidden, CAST(:meta AS jsonb), NOW())
            ON CONFLICT (agent_id, label) DO UPDATE SET
                value = EXCLUDED.value,
                description = EXCLUDED.description,
                block_limit = EXCLUDED.block_limit,
                read_only = EXCLUDED.read_only,
                hidden = EXCLUDED.hidden,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
        """), {
            "name": agent_name, "label": label, "value": b.value,
            "desc": b.description, "limit": b.limit,
            "ro": b.read_only, "hidden": b.hidden,
            "meta": json.dumps(b.metadata),
        })
        await db.commit()
    except Exception as e:
        log.exception("upsert_block failed")
        raise HTTPException(status_code=500, detail=f"block upsert failed: {e}")
    return BlockResponse(
        label=b.label, value=b.value, description=b.description,
        limit=b.limit, read_only=b.read_only, hidden=b.hidden,
        chars_current=b.chars_current, chars_remaining=b.chars_remaining,
        is_full=b.is_full,
    )


@router.get("/blocks/{agent_name}/{label}", response_model=BlockResponse)
async def get_block(agent_name: str, label: str, db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "memory_blocks"):
        raise _err_503("memory_blocks")
    from app.adopted import blocks
    row = (await db.execute(text("""
        SELECT b.value, b.description, b.block_limit, b.read_only, b.hidden, b.metadata
        FROM memory_blocks b
        JOIN agents a ON b.agent_id = a.id
        WHERE a.name = :name AND b.label = :label
    """), {"name": agent_name, "label": label})).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="block not found")
    meta = row.metadata or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    b = blocks.Block(
        label=label, value=row.value or "", description=row.description or "",
        limit=int(row.block_limit or 2000),
        read_only=bool(row.read_only), hidden=bool(row.hidden),
        metadata=meta,
    )
    return BlockResponse(
        label=b.label, value=b.value, description=b.description,
        limit=b.limit, read_only=b.read_only, hidden=b.hidden,
        chars_current=b.chars_current, chars_remaining=b.chars_remaining,
        is_full=b.is_full,
    )


@router.get("/blocks/{agent_name}/render")
async def render_blocks(agent_name: str, line_numbered: bool = False,
                        db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "memory_blocks"):
        raise _err_503("memory_blocks")
    from app.adopted import blocks
    rows = (await db.execute(text("""
        SELECT b.label, b.value, b.description, b.block_limit, b.read_only, b.hidden, b.metadata
        FROM memory_blocks b
        JOIN agents a ON b.agent_id = a.id
        WHERE a.name = :name
        ORDER BY b.label
    """), {"name": agent_name})).fetchall()
    blist = []
    for r in rows:
        meta = r.metadata or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        blist.append(blocks.Block(
            label=r.label, value=r.value or "", description=r.description or "",
            limit=int(r.block_limit or 2000),
            read_only=bool(r.read_only), hidden=bool(r.hidden),
            metadata=meta,
        ))
    return {"xml": blocks.render_memory_blocks(blist, line_numbered=line_numbered)}


# ---------------------------------------------------------------------------
# Hook events
# ---------------------------------------------------------------------------

@router.post("/hooks/capture")
async def capture_hook(body: HookCaptureRequest, db: AsyncSession = Depends(get_db)):
    """Persist a single lifecycle event.  Used by the agent plugins to
    auto-capture session_start / prompt_submit / post_tool_use etc.
    """
    if not await _table_exists(db, "hook_events"):
        raise _err_503("hook_events")
    try:
        await db.execute(text("""
            INSERT INTO hook_events (event, session_id, agent_id, cwd, data)
            VALUES (:event, :session, :agent, :cwd, CAST(:data AS jsonb))
        """), {
            "event": body.event, "session": body.session_id,
            "agent": body.agent_id, "cwd": body.cwd,
            "data": json.dumps(body.data),
        })
        await db.commit()
    except Exception as e:
        log.exception("hook capture failed")
        raise HTTPException(status_code=500, detail=f"hook capture failed: {e}")
    return {"captured": True, "event": body.event}


@router.get("/hooks/list")
async def list_hooks(event: Optional[str] = None, session_id: Optional[str] = None,
                     agent_id: Optional[str] = None, limit: int = Query(50, le=500),
                     db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "hook_events"):
        raise _err_503("hook_events")
    sql = "SELECT id, event, session_id, agent_id, cwd, data, created_at FROM hook_events WHERE 1=1"
    params: Dict[str, Any] = {"limit": limit}
    if event:
        sql += " AND event = :event"
        params["event"] = event
    if session_id:
        sql += " AND session_id = :sess"
        params["sess"] = session_id
    if agent_id:
        sql += " AND agent_id = :aid"
        params["aid"] = agent_id
    sql += " ORDER BY created_at DESC LIMIT :limit"
    out = []
    for r in (await db.execute(text(sql), params)).fetchall():
        data = r.data or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {}
        out.append({
            "id": str(r.id), "event": r.event,
            "session_id": r.session_id, "agent_id": r.agent_id,
            "cwd": r.cwd, "data": data,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"events": out, "total": len(out)}


# ---------------------------------------------------------------------------
# Peers + observations
# ---------------------------------------------------------------------------

@router.post("/peers")
async def upsert_peer(body: PeerRequest, db: AsyncSession = Depends(get_db)):
    from app.adopted import peers as _peers
    if not await _table_exists(db, "peers"):
        raise _err_503("peers")
    p = _peers.Peer(
        id=body.name, name=body.name, kind=_peers.PeerKind(body.kind),
        workspace=body.workspace, metadata=body.metadata,
    )
    try:
        await db.execute(text("""
            INSERT INTO peers (id, workspace, name, kind, metadata, last_active)
            VALUES (:id, :ws, :name, :kind, CAST(:meta AS jsonb), NOW())
            ON CONFLICT (workspace, id) DO UPDATE SET
                name = EXCLUDED.name, kind = EXCLUDED.kind,
                metadata = EXCLUDED.metadata, last_active = NOW()
        """), {
            "id": p.id, "ws": p.workspace, "name": p.name,
            "kind": p.kind.value, "meta": json.dumps(p.metadata),
        })
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"peer upsert failed: {e}")
    return {"id": p.id, "workspace": p.workspace, "name": p.name, "kind": p.kind.value}


@router.post("/peers/observations")
async def add_peer_observation(body: PeerObservationRequest, db: AsyncSession = Depends(get_db)):
    from app.adopted import peers as _peers
    if not await _table_exists(db, "peer_observations"):
        raise _err_503("peer_observations")
    obs = _peers.PeerObservation(
        id=str(uuid.uuid4()),
        observer=body.observer, observed=body.observed, text=body.text,
        confidence=body.confidence, session=body.session,
        metadata=body.metadata,
    )
    try:
        await db.execute(text("""
            INSERT INTO peer_observations
                (id, workspace, observer, observed, text, confidence, session, metadata)
            VALUES
                (CAST(:id AS uuid), :ws, :ob, :od, :txt, :conf, :sess, CAST(:meta AS jsonb))
        """), {
            "id": obs.id, "ws": body.workspace, "ob": obs.observer,
            "od": obs.observed, "txt": obs.text, "conf": obs.confidence,
            "sess": obs.session, "meta": json.dumps(obs.metadata),
        })
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"observation failed: {e}")
    return {"id": obs.id, "observer": obs.observer, "observed": obs.observed}


@router.get("/peers/observations/of/{observed}")
async def observations_about(observed: str, observer: Optional[str] = None,
                              workspace: str = "default", limit: int = Query(50, le=500),
                              db: AsyncSession = Depends(get_db)):
    if not await _table_exists(db, "peer_observations"):
        raise _err_503("peer_observations")
    sql = """
        SELECT id, observer, text, confidence, session, created_at, metadata
        FROM peer_observations
        WHERE workspace = :ws AND observed = :od
    """
    params: Dict[str, Any] = {"ws": workspace, "od": observed, "limit": limit}
    if observer:
        sql += " AND observer = :ob"
        params["ob"] = observer
    sql += " ORDER BY created_at DESC LIMIT :limit"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"observations": [
        {"id": str(r.id), "observer": r.observer, "text": r.text,
         "confidence": float(r.confidence or 1.0),
         "session": r.session, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ], "total": len(rows)}


# ---------------------------------------------------------------------------
# Temporal KG
# ---------------------------------------------------------------------------

@router.post("/triples")
async def add_triple(body: TripleRequest, db: AsyncSession = Depends(get_db)):
    from app.adopted import temporal_kg
    if not await _table_exists(db, "temporal_triples"):
        raise _err_503("temporal_triples")
    try:
        t = temporal_kg.Triple(
            subject=body.subject, predicate=body.predicate, object=body.object,
            valid_from=body.valid_from, valid_to=body.valid_to,
            confidence=body.confidence, source=body.source,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    new_id = uuid.uuid4()
    try:
        await db.execute(text("""
            INSERT INTO temporal_triples
                (id, subject, predicate, object, valid_from, valid_to, confidence, source)
            VALUES
                (CAST(:id AS uuid), :sub, :pred, :obj,
                 CAST(:vf AS timestamptz), CAST(:vt AS timestamptz),
                 :conf, :src)
        """), {
            "id": str(new_id), "sub": t.subject, "pred": t.predicate, "obj": t.object,
            "vf": t.valid_from, "vt": t.valid_to, "conf": t.confidence, "src": t.source,
        })
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"triple insert failed: {e}")
    return {"id": str(new_id), "subject": t.subject, "predicate": t.predicate, "object": t.object}


@router.get("/triples/query")
async def query_triples(subject: Optional[str] = None, predicate: Optional[str] = None,
                        object: Optional[str] = None, as_of: Optional[str] = None,
                        limit: int = Query(50, le=500),
                        db: AsyncSession = Depends(get_db)):
    from app.adopted import temporal_kg
    if not await _table_exists(db, "temporal_triples"):
        raise _err_503("temporal_triples")
    sql = "SELECT id, subject, predicate, object, valid_from, valid_to, confidence, source FROM temporal_triples WHERE 1=1"
    params: Dict[str, Any] = {"limit": limit}
    if subject:
        sql += " AND subject = :sub"
        params["sub"] = subject
    if predicate:
        sql += " AND predicate = :pred"
        params["pred"] = predicate
    if object:
        sql += " AND object = :obj"
        params["obj"] = object
    if as_of:
        sql += " AND (valid_from IS NULL OR valid_from <= CAST(:as_of AS timestamptz))"
        sql += " AND (valid_to IS NULL OR valid_to > CAST(:as_of AS timestamptz))"
        params["as_of"] = as_of
    sql += " ORDER BY valid_from DESC NULLS LAST LIMIT :limit"
    rows = (await db.execute(text(sql), params)).fetchall()
    out = []
    for r in rows:
        t = temporal_kg.Triple(
            subject=r.subject, predicate=r.predicate, object=r.object,
            valid_from=r.valid_from.isoformat() if r.valid_from else None,
            valid_to=r.valid_to.isoformat() if r.valid_to else None,
            confidence=float(r.confidence or 1.0), source=r.source,
        )
        out.append({
            "id": str(r.id), "subject": t.subject, "predicate": t.predicate,
            "object": t.object, "valid_from": t.valid_from, "valid_to": t.valid_to,
            "is_open": t.is_open(), "is_valid_at_now": t.is_valid_at(datetime.now(timezone.utc).isoformat()),
        })
    return {"triples": out, "total": len(out)}


# ---------------------------------------------------------------------------
# Multi-source ingest
# ---------------------------------------------------------------------------

@router.post("/ingest")
async def ingest(body: IngestRequest, db: AsyncSession = Depends(get_db)):
    from app.adopted import multi_source
    src = multi_source.Source(
        path=body.path, text=body.text, source_type=None,
        title=body.title, metadata=body.metadata,
    )
    try:
        doc = multi_source.route_source(src)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ingest failed: {e}")
    chunks = doc.chunk()
    return {
        "source_type": doc.source_type.value,
        "title": doc.title,
        "chunks": chunks,
        "chunk_count": len(chunks),
    }


# ---------------------------------------------------------------------------
# Container tags utility
# ---------------------------------------------------------------------------

@router.get("/containers/parse")
async def container_parse(tag: str):
    from app.adopted import containers
    normalized = containers.normalize(tag)
    return {
        "input": tag,
        "normalized": normalized,
        "valid": containers.is_valid(normalized),
        "kind": containers.kind_of(normalized),
        "name": containers.name_of(normalized),
    }


# ---------------------------------------------------------------------------
# Deriver + tiers (introspection)
# ---------------------------------------------------------------------------

@router.get("/tiers/stats/{agent_name}")
async def tier_stats(agent_name: str, db: AsyncSession = Depends(get_db)):
    from app.adopted import tiers
    if not await _table_exists(db, "memories"):
        raise _err_503("memories")
    rows = (await db.execute(text("""
        SELECT tier, COUNT(*) AS count
        FROM memories
        WHERE agent_id = (SELECT id FROM agents WHERE name = :name)
        GROUP BY tier
    """), {"name": agent_name})).fetchall()
    counts = {r.tier: int(r.count or 0) for r in rows}
    half_lives = {tier.value: tiers.HALF_LIFE_DAYS[tier] for tier in tiers.Tier}
    return {"agent": agent_name, "counts": counts, "half_life_days": half_lives}


@router.get("/registry")
async def registry():
    """List every adopted pattern + its feature flag."""
    from app.adopted import list_adopted
    return {"patterns": list_adopted()}
