"""Memory routes — save, recall, reflect, delete."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

log = logging.getLogger("nexus.routers.memory")

try:
    from opentelemetry import trace as _otel_trace
    _tracer = _otel_trace.get_tracer("nexus.memory")
except ImportError:
    _tracer = None
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text
from app.db import get_db, SessionLocal
from app.models.api import (
    MemorySaveRequest, MemorySaveResponse,
    MemoryBatchSaveRequest, MemoryBatchSaveResponse,
    MemoryRecallRequest, MemoryRecallResponse,
    MemoryRecallDebugResponse,
    MemoryReflectRequest, MemoryReflectResponse,
)
from app.memory.ingest import save_memory, bump_access
from app.memory.reflect import reflect as do_reflect
from app.search.vector import vector_search
from app.search.lexical import lexical_search
from app.search.graph import graph_search
from app.search.temporal import temporal_search
from app.search.fusion import reciprocal_rank_fusion
from app.search.expand import is_trivial_query, expand_query
from app.search.rerank import rerank as rerank_results


def _apply_adopted_filters(fused):
    """Apply the adopted-pattern filters: expiration + decay-strength re-rank.

    - `expiration_date` memories are dropped (auto-forgetting).
    - Each result's `importance` is multiplied by a decay score from
      `app.adopted.decay` so frequently-accessed memories float up.
    """
    try:
        from app.adopted import expiration, decay
    except ImportError:
        return fused
    out = []
    for m in fused:
        meta = getattr(m, "metadata", None) or {}
        if expiration.is_expired({"metadata": meta} if not isinstance(meta, dict) else meta):
            continue
        if hasattr(m, "id"):
            try:
                meta_dict = dict(meta) if not isinstance(meta, dict) else meta
                state = decay.ConnectionState(
                    strength=float(getattr(m, "importance", 0.5) or 0.5),
                    stability=float(meta_dict.get("stability", 30.0) or 30.0),
                    last_activated=getattr(m, "accessed_at", None),
                    access_count=int(getattr(m, "access_count", 0) or 0),
                )
                if hasattr(m, "relevance") and m.relevance is not None:
                    m.relevance = float(m.relevance) * decay.score(state)
            except Exception:
                pass
        out.append(m)
    return out


router = APIRouter()


async def _search_in_own_session(fn, *args):
    """Run a search function with its own isolated DB session."""
    async with SessionLocal() as db:
        return await fn(db, *args)


@router.post("/save", response_model=MemorySaveResponse)
async def save(body: MemorySaveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await save_memory(db, request.app.state.redis, body)
    # Auto-link the new memory to any code symbols it mentions.
    try:
        from app.code.links import auto_link_memory_to_symbols
        if result.id:
            await auto_link_memory_to_symbols(db, str(result.id), body.content or "")
    except Exception as e:
        log.debug("auto-link failed: %s", e)
    return result


@router.post("/batch", response_model=MemoryBatchSaveResponse)
async def batch_save(body: MemoryBatchSaveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    results: list[MemorySaveResponse] = []
    for item in body.memories:
        results.append(await save_memory(db, request.app.state.redis, item))
    return MemoryBatchSaveResponse(
        results=results,
        total=len(body.memories),
        saved=sum(1 for r in results if not r.deduplicated),
        deduplicated=sum(1 for r in results if r.deduplicated),
    )


@router.post("/recall", response_model=MemoryRecallResponse)
async def recall(body: MemoryRecallRequest):
    """Recall memories with a cheaper two-phase strategy.

    Vector + lexical run first. Graph + temporal are only used when the primary
    searches are sparse, unless the caller explicitly requests only secondary
    modes.

    This endpoint is now always direct recall against the memory store.
    """
    if is_trivial_query(body.query):
        return MemoryRecallResponse(results=[], total=0, modes_used=[])

    modes = body.search_modes or ["vector", "lexical", "graph", "temporal"]
    used: list[str] = []
    lists = []

    expanded_query = await expand_query(body.query)

    primary_tasks = []
    primary_names = []
    if "vector" in modes:
        primary_tasks.append(_search_in_own_session(
            vector_search, expanded_query, body.agent_id, body.memory_types, body.limit * 2
        ))
        primary_names.append("vector")
    if "lexical" in modes:
        primary_tasks.append(_search_in_own_session(
            lexical_search, body.query, body.agent_id, body.memory_types, body.limit * 2
        ))
        primary_names.append("lexical")

    if primary_tasks:
        raw = await asyncio.gather(*primary_tasks, return_exceptions=True)
        for name, result in zip(primary_names, raw):
            if not isinstance(result, Exception):
                used.append(name)
                if result:
                    lists.append(result)

    fused = reciprocal_rank_fusion(lists)[: body.limit]

    secondary_requested = [m for m in ("graph", "temporal") if m in modes]
    should_expand = (not primary_tasks) or len(fused) < body.limit
    # If primary recall is very sparse, run both secondary modes; if it is close
    # to enough, run only requested secondaries until we can fill the limit.
    if secondary_requested and should_expand:
        secondary_tasks = []
        secondary_names = []
        if "graph" in secondary_requested and (len(fused) < max(1, body.limit // 2) or not primary_tasks):
            secondary_tasks.append(_search_in_own_session(graph_search, body.query, body.agent_id, body.limit))
            secondary_names.append("graph")
        if "temporal" in secondary_requested:
            secondary_tasks.append(_search_in_own_session(
                temporal_search, body.query, body.agent_id, body.memory_types, body.limit
            ))
            secondary_names.append("temporal")

        if secondary_tasks:
            raw = await asyncio.gather(*secondary_tasks, return_exceptions=True)
            for name, result in zip(secondary_names, raw):
                if not isinstance(result, Exception):
                    used.append(name)
                    if result:
                        lists.append(result)
            fused = reciprocal_rank_fusion(lists)[: body.limit]

    fused = await rerank_results(body.query, fused, body.limit)

    # Adopted-pattern filters — expiration + decay-strength re-rank.
    fused = _apply_adopted_filters(fused)

    # Honesty gate: drop weak matches so recall returns recognition, not noise.
    # When nothing clears the bar, return empty — "I don't have that" beats a guess.
    from app.config import settings as _gate
    min_rel = body.min_relevance if body.min_relevance > 0 else _gate.recall_min_relevance
    if min_rel > 0:
        fused = [m for m in fused if (m.relevance or 0.0) >= min_rel]

    if fused:
        task = asyncio.create_task(_bump_async([m.id for m in fused]))
        task.add_done_callback(lambda t: log.warning("bump_access failed: %s", t.exception()) if t.exception() else None)

    from app.config import settings as _s
    fusion_label = f"rrf+{_s.reranker_provider}-rerank" if _s.reranker_enabled else "rrf"

    if _tracer:
        span = _otel_trace.get_current_span()
        span.set_attribute("nexus.recall.agent_id", body.agent_id or "")
        span.set_attribute("nexus.recall.modes", ",".join(used))
        span.set_attribute("nexus.recall.result_count", len(fused))
        span.set_attribute("nexus.recall.reranker", fusion_label)

    return MemoryRecallResponse(results=fused, total=len(fused), modes_used=used, fusion=fusion_label)


@router.post("/recall/debug", response_model=MemoryRecallDebugResponse)
async def recall_debug(body: MemoryRecallRequest):
    """Recall lab endpoint: return per-mode candidates plus fused/reranked rankings."""
    if is_trivial_query(body.query):
        return MemoryRecallDebugResponse(
            query=body.query,
            expanded_query=body.query,
            agent_id=body.agent_id,
            modes_requested=body.search_modes or [],
            explanation={"trivial_query": True},
        )

    modes = body.search_modes or ["vector", "lexical", "graph", "temporal"]
    expanded_query = await expand_query(body.query)
    tasks = []
    names = []
    if "vector" in modes:
        names.append("vector")
        tasks.append(_search_in_own_session(vector_search, expanded_query, body.agent_id, body.memory_types, body.limit * 2))
    if "lexical" in modes:
        names.append("lexical")
        tasks.append(_search_in_own_session(lexical_search, body.query, body.agent_id, body.memory_types, body.limit * 2))
    if "graph" in modes:
        names.append("graph")
        tasks.append(_search_in_own_session(graph_search, body.query, body.agent_id, body.limit * 2))
    if "temporal" in modes:
        names.append("temporal")
        tasks.append(_search_in_own_session(temporal_search, body.query, body.agent_id, body.memory_types, body.limit * 2))

    raw = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    per_mode = {}
    lists = []
    errors = {}
    for name, result in zip(names, raw):
        if isinstance(result, Exception):
            per_mode[name] = []
            errors[name] = str(result)
            continue
        per_mode[name] = result[: body.limit]
        if result:
            lists.append(result)

    fused_full = reciprocal_rank_fusion(lists)
    fused = fused_full[: body.limit]
    reranked = await rerank_results(body.query, fused_full, body.limit)
    fusion_label = "rrf+llm-rerank" if __import__("app.config", fromlist=["settings"]).settings.reranker_enabled else "rrf"
    return MemoryRecallDebugResponse(
        query=body.query,
        expanded_query=expanded_query,
        agent_id=body.agent_id,
        modes_requested=modes,
        per_mode=per_mode,
        fused=fused,
        reranked=reranked,
        fusion=fusion_label,
        explanation={
            "mode_counts": {k: len(v) for k, v in per_mode.items()},
            "errors": errors,
            "rrf_inputs": len(lists),
            "limit": body.limit,
            "reranker_enabled": fusion_label != "rrf",
        },
    )


async def _bump_async(ids: list[str]):
    async with SessionLocal() as db:
        await bump_access(db, ids)


@router.post("/reflect", response_model=MemoryReflectResponse)
async def reflect_endpoint(body: MemoryReflectRequest):
    vec, lex = await asyncio.gather(
        _search_in_own_session(vector_search, body.query, body.agent_id, None, 12),
        _search_in_own_session(lexical_search, body.query, body.agent_id, None, 8),
        return_exceptions=True,
    )
    all_results = []
    if not isinstance(vec, Exception):
        all_results.extend(vec)
    if not isinstance(lex, Exception):
        all_results.extend(lex)
    fused = reciprocal_rank_fusion([all_results])[:15]
    return await do_reflect(body, fused)


@router.post("/{memory_id}/confirm")
async def confirm_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a memory as confirmed — boosts its trust score in future retrieval."""
    result = await db.execute(
        text("""UPDATE memories SET confirmed_count = confirmed_count + 1,
                importance = LEAST(1.0, importance + 0.03)
                WHERE id = CAST(:id AS uuid) RETURNING id, confirmed_count"""),
        {"id": memory_id},
    )
    row = result.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": str(row.id), "confirmed_count": row.confirmed_count}


@router.post("/{memory_id}/contradict")
async def contradict_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a memory as contradicted — demotes its trust score in future retrieval."""
    result = await db.execute(
        text("""UPDATE memories SET contradicted_count = contradicted_count + 1,
                importance = GREATEST(0.05, importance - 0.05)
                WHERE id = CAST(:id AS uuid) RETURNING id, contradicted_count"""),
        {"id": memory_id},
    )
    row = result.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": str(row.id), "contradicted_count": row.contradicted_count}


@router.get("/profile/{agent_id}")
async def agent_profile(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Return all facts about an agent — no query needed. Cold-start friendly."""
    rows = await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance, m.access_count,
               m.confirmed_count, m.contradicted_count, m.created_at, m.metadata
        FROM memories m
        JOIN agents a ON m.agent_id = a.id
        WHERE a.name = :name
        ORDER BY
            CASE memory_type WHEN 'lesson' THEN 0 WHEN 'preference' THEN 1
                 WHEN 'observation' THEN 2 ELSE 3 END,
            importance DESC, access_count DESC
        LIMIT 50
    """), {"name": agent_id})

    rep_row = await db.execute(
        text("SELECT representation FROM agents WHERE name = :name"), {"name": agent_id}
    )
    rep = rep_row.scalar()

    conc_rows = await db.execute(text("""
        SELECT content FROM conclusions c
        JOIN agents a ON c.agent_id = a.id WHERE a.name = :name
        ORDER BY c.created_at DESC LIMIT 20
    """), {"name": agent_id})

    memories = []
    by_type: dict[str, int] = {}
    for r in rows.fetchall():
        by_type[r.memory_type] = by_type.get(r.memory_type, 0) + 1
        memories.append({
            "id": str(r.id), "content": r.content, "memory_type": r.memory_type,
            "importance": float(r.importance), "access_count": r.access_count,
            "confirmed": r.confirmed_count or 0, "contradicted": r.contradicted_count or 0,
        })

    return {
        "agent_id": agent_id,
        "representation": rep,
        "conclusions": [r.content for r in conc_rows.fetchall()],
        "memories": memories,
        "total": len(memories),
        "by_type": by_type,
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM memories WHERE id = CAST(:id AS uuid) RETURNING id"),
        {"id": memory_id},
    )
    row = result.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": str(row.id)}


# ── Memory Iris Gate ────────────────────────────────────────────────────

class MemoryIrisRequest(BaseModel):
    query: Optional[str] = None
    agent_id: Optional[str] = None
    layer: Optional[str] = None  # L1/L2/L3
    rung: int = Field(2, ge=1, le=4)
    justification: Optional[str] = None
    limit: int = Field(50, le=500)
    memory_ids: Optional[List[str]] = None


@router.post("/iris")
async def memory_iris_gate(
    body: MemoryIrisRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Memory Iris Gate — 4-rung context escalation for memories.

    Rungs:
      1 - count only
      2 - metadata: id, type, importance, agent
      3 - summary: metadata + first 200 chars of content
      4 - full: complete content (requires justification)
    """
    from app.memory.iris import memory_iris
    if body.rung == 4 and not body.justification:
        raise HTTPException(400, "rung 4 (full content) requires justification")
    return await memory_iris(
        db,
        query=body.query,
        agent_id=body.agent_id,
        layer=body.layer,
        rung=body.rung,
        justification=body.justification,
        limit=body.limit,
        memory_ids=body.memory_ids,
    )
