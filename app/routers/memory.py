"""Memory routes — save, recall, reflect, delete."""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request, Depends

log = logging.getLogger("nexus.routers.memory")
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text
from app.db import get_db, SessionLocal
from app.models.api import (
    MemorySaveRequest, MemorySaveResponse,
    MemoryBatchSaveRequest, MemoryBatchSaveResponse,
    MemoryRecallRequest, MemoryRecallResponse,
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

router = APIRouter()


async def _search_in_own_session(fn, *args):
    """Run a search function with its own isolated DB session."""
    async with SessionLocal() as db:
        return await fn(db, *args)


@router.post("/save", response_model=MemorySaveResponse)
async def save(body: MemorySaveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    return await save_memory(db, request.app.state.redis, body)


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

    if fused:
        task = asyncio.create_task(_bump_async([m.id for m in fused]))
        task.add_done_callback(lambda t: log.warning("bump_access failed: %s", t.exception()) if t.exception() else None)

    return MemoryRecallResponse(results=fused, total=len(fused), modes_used=used)


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
