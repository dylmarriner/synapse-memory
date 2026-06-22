"""Entity graph traversal — find memories connected through named entities."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import MemoryResult

log = logging.getLogger("nexus.search.graph")


async def graph_search(
    db: AsyncSession,
    query: str,
    agent_id: Optional[str] = None,
    limit: int = 20,
) -> List[MemoryResult]:
    """Find memories connected to entities mentioned in the query."""
    tokens = [t.strip(".,!?;:'\"()[]{}") for t in query.split() if len(t.strip(".,!?;:'\"()[]{}")) > 3]
    if not tokens:
        return []

    params: dict = {"limit": limit}
    tok_conditions = []
    for i, tok in enumerate(tokens[:6]):
        params[f"tok{i}"] = f"%{tok}%"
        tok_conditions.append(f"LOWER(e.name) LIKE LOWER(:tok{i})")

    agent_filter = ""
    if agent_id:
        agent_filter = "AND e.agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)"
        params["agent_name"] = agent_id

    entity_condition = " OR ".join(tok_conditions)

    sql = text(f"""
        SELECT DISTINCT ON (m.id)
               m.id, m.content, m.memory_type, m.agent_id,
               m.importance, m.access_count, m.created_at, m.metadata,
               m.confidence, m.valid_from, m.valid_until, m.extraction_model,
               0.6 AS score
        FROM memories m
        JOIN relations r  ON r.memory_id = m.id
        JOIN entities e   ON e.id = r.from_entity_id OR e.id = r.to_entity_id
        WHERE ({entity_condition}) {agent_filter}
        ORDER BY m.id, m.importance DESC, m.created_at DESC
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            MemoryResult(
                id=str(r.id),
                content=r.content,
                score=0.6,
                memory_type=r.memory_type,
                agent_id=str(r.agent_id) if r.agent_id else None,
                importance=float(r.importance),
                access_count=r.access_count,
                created_at=r.created_at,
                metadata=r.metadata or {},
                matched_by=["graph"],
                confidence=float(r.confidence) if r.confidence is not None else 1.0,
                valid_from=r.valid_from,
                valid_until=r.valid_until,
                extraction_model=r.extraction_model,
            )
            for r in rows
        ]
    except Exception as e:
        log.warning("Graph search failed: %s", e)
        return []
