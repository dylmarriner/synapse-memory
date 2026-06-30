"""Memory Iris Gate — the same 4-rung context escalation pattern that
applies to code symbols, but for memory records.

Rungs:
  1 - count only: just the number of matching memories, no data
  2 - metadata: id, type, tags, importance, age — no content
  3 - summary: metadata + first 200 chars of content
  4 - full: complete content (rung 4 requires justification)

This is the mirror of `app.code.cards.iris_gate` but for memories,
keeping the same 4-rung pattern across the system.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.memory.iris")


async def memory_iris(
    db: AsyncSession,
    query: Optional[str] = None,
    agent_id: Optional[str] = None,
    layer: Optional[str] = None,
    rung: int = 2,
    justification: Optional[str] = None,
    limit: int = 50,
    memory_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Memory Iris Gate.  Returns memories at the requested rung.

    If `memory_ids` is provided, query those directly.  Otherwise recall
    via the agent's recent memories (filtered by query/agent/layer).
    """
    rung = max(1, min(4, rung))

    # Step 1: collect the candidate memory IDs via recall
    if memory_ids is None:
        memory_ids = await _recall_ids(db, query, agent_id, layer, limit)

    total = len(memory_ids)
    bytes_used = 0
    payload: List[Dict[str, Any]] = []

    if rung == 1:
        # Just the count, no rows
        return {"rung": 1, "count": total, "bytes": 24, "est_tokens": 6}

    # Fetch rows in batch for the higher rungs
    if not memory_ids:
        return {"rung": rung, "count": 0, "memories": [], "bytes": 0, "est_tokens": 0}
    rows = (await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance, m.confidence,
               m.access_count, m.created_at, m.agent_id
        FROM memories m WHERE m.id::text = ANY(:ids)
        ORDER BY m.importance DESC, m.created_at DESC
    """), {"ids": memory_ids})).fetchall()

    for r in rows:
        mem_id, content, mtype, importance, confidence, access_count, created_at, agent_id = r
        if rung == 2:
            row = {
                "id": str(mem_id),
                "memory_type": mtype,
                "importance": float(importance or 0),
                "confidence": float(confidence or 0),
                "access_count": int(access_count or 0),
                "agent_id": agent_id,
                "created_at": created_at.isoformat() if created_at else None,
            }
        elif rung == 3:
            summary = (content or "")[:200]
            row = {
                "id": str(mem_id),
                "memory_type": mtype,
                "importance": float(importance or 0),
                "summary": summary,
                "agent_id": agent_id,
                "created_at": created_at.isoformat() if created_at else None,
            }
        else:  # rung 4
            row = {
                "id": str(mem_id),
                "content": content or "",
                "memory_type": mtype,
                "importance": float(importance or 0),
                "confidence": float(confidence or 0),
                "access_count": int(access_count or 0),
                "agent_id": agent_id,
                "created_at": created_at.isoformat() if created_at else None,
            }
        payload.append(row)
        bytes_used += len(str(row))
        if bytes_used > 100_000:  # safety cap
            break

    if rung == 4 and not justification:
        return {
            "rung": 4,
            "error": "rung 4 (full content) requires justification",
            "count": total,
        }

    return {
        "rung": rung,
        "count": total,
        "memories": payload,
        "bytes": bytes_used,
        "est_tokens": int(bytes_used * 0.25),
    }


async def _recall_ids(
    db: AsyncSession, query: Optional[str], agent_id: Optional[str],
    layer: Optional[str], limit: int,
) -> List[str]:
    """Get memory IDs using the existing recall path."""
    if not query and not agent_id and not layer:
        # Without a filter, return empty — agents must scope their recall
        return []
    where = []
    params: Dict[str, Any] = {"limit": limit}
    if query:
        where.append("m.content ILIKE :q")
        params["q"] = f"%{query}%"
    if agent_id:
        where.append("a.name = :aid")
        params["aid"] = agent_id
    if layer:
        where.append("ml.layer = :layer")
        params["layer"] = layer
    where_sql = " AND ".join(where) if where else "TRUE"
    join_layer = "LEFT JOIN memory_layers ml ON ml.memory_id = m.id" if layer else ""
    join_agent = "LEFT JOIN agents a ON a.id = m.agent_id" if agent_id else ""
    rows = (await db.execute(text(f"""
        SELECT m.id::text
        FROM memories m
        {join_agent}
        {join_layer}
        WHERE {where_sql}
        ORDER BY m.importance DESC, m.created_at DESC
        LIMIT :limit
    """), params)).fetchall()
    return [r[0] for r in rows]


__all__ = ["memory_iris"]
