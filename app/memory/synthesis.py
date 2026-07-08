"""Knowledge synthesis — deterministic topic synthesis stored as text."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import MemoryResult

log = logging.getLogger("nexus.memory.synthesis")


async def synthesize_topic(
    db: AsyncSession,
    topic: str,
    agent_id: Optional[str] = None,
    limit: int = 30,
) -> Optional[str]:
    """Synthesize all memories on a topic into a single knowledge document."""
    from app.search.lexical import lexical_search
    from app.search.vector import vector_search
    from app.search.fusion import reciprocal_rank_fusion
    import asyncio

    vec, lex = await asyncio.gather(
        vector_search(db, topic, agent_id, limit=limit),
        lexical_search(db, topic, agent_id, limit=limit),
        return_exceptions=True,
    )

    lists = []
    if not isinstance(vec, Exception):
        lists.append(vec)
    if not isinstance(lex, Exception):
        lists.append(lex)

    if not lists:
        return None

    fused = reciprocal_rank_fusion(lists)[:limit]
    if not fused:
        return None

    by_type: dict[str, int] = {}
    lines: list[str] = []
    for memory in fused[:15]:
        by_type[memory.memory_type] = by_type.get(memory.memory_type, 0) + 1
        lines.append(f"- [{memory.memory_type}] {memory.content[:320]}")
    header = [f"Knowledge summary for '{topic}'", f"Agent scope: {agent_id or 'all'}", f"Evidence count: {len(fused)}"]
    if by_type:
        header.append("Memory mix: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    return "\n".join(header + ["", *lines])
