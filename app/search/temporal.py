"""Temporal search — recency + importance weighted recall with keyword pre-filter."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import MemoryResult

log = logging.getLogger("nexus.search.temporal")


async def temporal_search(
    db: AsyncSession,
    query: str,
    agent_id: Optional[str] = None,
    memory_types: Optional[List[str]] = None,
    limit: int = 20,
) -> List[MemoryResult]:
    """Recency + importance weighted recall."""
    tokens = [t.lower().strip(".,!?;:'\"") for t in query.split() if len(t) > 3]
    conditions = [
        "superseded_by IS NULL",
        "(valid_until IS NULL OR valid_until > NOW())",
    ]
    params: dict = {"limit": limit}

    if tokens:
        tok_conditions = []
        for i, tok in enumerate(tokens[:4]):
            params[f"tok{i}"] = f"%{tok}%"
            tok_conditions.append(f"LOWER(content) LIKE :tok{i}")
        conditions.append(f"({' OR '.join(tok_conditions)})")

    if agent_id:
        conditions.append("agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)")
        params["agent_name"] = agent_id

    if memory_types:
        conditions.append("memory_type = ANY(:types)")
        params["types"] = memory_types

    where = "WHERE " + " AND ".join(conditions)

    sql = text(f"""
        SELECT id, content, memory_type, agent_id, importance, access_count, created_at, metadata,
               confidence, valid_from, valid_until, extraction_model,
               (importance * 0.5 +
                GREATEST(0.0, 1.0 - EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0) * 0.3 +
                LEAST(1.0, access_count / 10.0) * 0.2) AS score
        FROM memories
        {where}
        ORDER BY created_at DESC, importance DESC
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            MemoryResult(
                id=str(r.id),
                content=r.content,
                score=max(0.0, float(r.score)),
                memory_type=r.memory_type,
                agent_id=str(r.agent_id) if r.agent_id else None,
                importance=float(r.importance),
                access_count=r.access_count,
                created_at=r.created_at,
                metadata=r.metadata or {},
                matched_by=["temporal"],
                confidence=float(r.confidence) if r.confidence is not None else 1.0,
                valid_from=r.valid_from,
                valid_until=r.valid_until,
                extraction_model=r.extraction_model,
            )
            for r in rows
        ]
    except Exception as e:
        log.warning("Temporal search failed: %s", e)
        return []
