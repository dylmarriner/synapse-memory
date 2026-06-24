"""BM25 / PostgreSQL full-text search for lexical recall."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import MemoryResult

log = logging.getLogger("nexus.search.lexical")


async def lexical_search(
    db: AsyncSession,
    query: str,
    agent_id: Optional[str] = None,
    memory_types: Optional[List[str]] = None,
    limit: int = 20,
) -> List[MemoryResult]:
    """PostgreSQL tsvector full-text search."""
    conditions = [
        "to_tsvector('english', content) @@ plainto_tsquery('english', :query)",
        "superseded_by IS NULL",
        "(valid_until IS NULL OR valid_until > NOW())",
    ]
    params: dict = {"query": query, "limit": limit}

    if agent_id:
        conditions.append("agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)")
        params["agent_name"] = agent_id

    if memory_types:
        conditions.append("memory_type = ANY(:types)")
        params["types"] = memory_types

    where = " AND ".join(conditions)
    sql = text(f"""
        SELECT id, content, memory_type, agent_id, importance, access_count, created_at, metadata,
               confidence, valid_from, valid_until, extraction_model,
               ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) AS score
        FROM memories
        WHERE {where}
        ORDER BY score DESC
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            MemoryResult(
                id=str(r.id),
                content=r.content,
                score=float(r.score),
                memory_type=r.memory_type,
                agent_id=str(r.agent_id) if r.agent_id else None,
                importance=float(r.importance),
                access_count=r.access_count,
                created_at=r.created_at,
                metadata=r.metadata or {},
                matched_by=["lexical"],
                confidence=float(r.confidence) if r.confidence is not None else 1.0,
                valid_from=r.valid_from,
                valid_until=r.valid_until,
                extraction_model=r.extraction_model,
            )
            for r in rows
        ]
    except Exception as e:
        log.warning("Lexical search failed: %s", e)
        return []
