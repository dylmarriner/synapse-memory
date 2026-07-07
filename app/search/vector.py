"""Semantic vector search using pgvector cosine similarity."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.api import MemoryResult
from app.embeddings import get_embedding

log = logging.getLogger("nexus.search.vector")


async def vector_search(
    db: AsyncSession,
    query: str,
    agent_id: Optional[str] = None,
    memory_types: Optional[List[str]] = None,
    limit: int = 20,
) -> List[MemoryResult]:
    """Cosine similarity search over memory embeddings."""
    embedding = await get_embedding(query)
    if embedding is None:
        return []

    conditions = ["embedding IS NOT NULL"]
    params: dict = {"emb": str(embedding), "limit": limit}

    if agent_id:
        conditions.append("agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)")
        params["agent_name"] = agent_id

    if memory_types:
        conditions.append("memory_type = ANY(:types)")
        params["types"] = memory_types

    where = " AND ".join(conditions)
    dims = settings.embedding_dims
    sql = text(f"""
        SELECT id, uri, content, memory_type, agent_id, importance, access_count, created_at, metadata,
               1 - (embedding <=> CAST(:emb AS vector({dims}))) AS score
        FROM memories
        WHERE {where}
        ORDER BY embedding <=> CAST(:emb AS vector({dims}))
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            MemoryResult(
                id=str(r.id),
                uri=getattr(r, 'uri', None),
                content=r.content,
                score=max(0.0, float(r.score)),
                memory_type=r.memory_type,
                agent_id=str(r.agent_id) if r.agent_id else None,
                importance=float(r.importance),
                access_count=r.access_count,
                created_at=r.created_at,
                metadata=r.metadata or {},
                matched_by=["vector"],
            )
            for r in rows
        ]
    except Exception as e:
        log.warning("Vector search failed: %s", e)
        return []
