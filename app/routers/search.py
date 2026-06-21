"""GET-based unified search endpoint."""

import asyncio
from typing import Optional
from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.api import MemoryRecallResponse
from app.search.vector import vector_search
from app.search.lexical import lexical_search
from app.search.graph import graph_search
from app.search.temporal import temporal_search
from app.search.fusion import reciprocal_rank_fusion

router = APIRouter()


async def _run(fn, *args):
    async with SessionLocal() as db:
        return await fn(db, *args)


@router.get("/", response_model=MemoryRecallResponse)
async def search(
    q: str,
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    modes: Optional[str] = Query(default=None, description="Comma-sep: vector,lexical,graph,temporal"),
):
    selected = set(modes.split(",")) if modes else {"vector", "lexical", "graph", "temporal"}

    tasks = []
    used: list[str] = []

    if "vector" in selected:
        tasks.append(_run(vector_search, q, agent_id, None, limit * 2))
        used.append("vector")
    if "lexical" in selected:
        tasks.append(_run(lexical_search, q, agent_id, None, limit * 2))
        used.append("lexical")
    if "graph" in selected:
        tasks.append(_run(graph_search, q, agent_id, limit))
        used.append("graph")
    if "temporal" in selected:
        tasks.append(_run(temporal_search, q, agent_id, None, limit))
        used.append("temporal")

    raw = await asyncio.gather(*tasks, return_exceptions=True)
    lists = [r for r in raw if not isinstance(r, Exception) and r]
    fused = reciprocal_rank_fusion(lists)[:limit]

    return MemoryRecallResponse(results=fused, total=len(fused), modes_used=used)
