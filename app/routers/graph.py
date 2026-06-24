"""Graph explorer — entity/relation data for the dashboard graph visualization."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

log = logging.getLogger("nexus.routers.graph")

router = APIRouter()


@router.get("/graph")
async def get_graph(
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return entity nodes and relation edges for graph visualization.

    Nodes are entities ranked by how many memories reference them.
    Edges are bi-temporal relations (excludes expired ones by default).
    """
    params: dict = {"limit": limit}
    agent_filter = ""
    if agent_id:
        agent_filter = "AND e.agent_id = (SELECT id FROM agents WHERE name = :agent_name LIMIT 1)"
        params["agent_name"] = agent_id

    node_rows = (await db.execute(text(f"""
        SELECT e.id, e.name, e.entity_type, e.created_at,
               COUNT(r.id) AS relation_count,
               COUNT(DISTINCT ms.memory_id) AS memory_count
        FROM entities e
        LEFT JOIN relations r ON r.from_entity_id = e.id OR r.to_entity_id = e.id
        LEFT JOIN (
            SELECT DISTINCT re.from_entity_id AS entity_id, rel.memory_id
            FROM relations re
            JOIN relations rel ON rel.from_entity_id = re.from_entity_id
            WHERE rel.memory_id IS NOT NULL
        ) ms ON ms.entity_id = e.id
        WHERE 1=1 {agent_filter}
        GROUP BY e.id, e.name, e.entity_type, e.created_at
        ORDER BY relation_count DESC, memory_count DESC
        LIMIT :limit
    """), params)).fetchall()

    node_ids = {str(r.id) for r in node_rows}

    if not node_ids:
        return {"nodes": [], "edges": [], "agent_id": agent_id}

    # Only return edges where both endpoints are in our node set
    edge_rows = (await db.execute(text(f"""
        SELECT r.id, r.from_entity_id, r.to_entity_id, r.relation_type,
               r.valid_from, r.valid_until, r.created_at, r.memory_id
        FROM relations r
        WHERE r.from_entity_id = ANY(:node_ids::uuid[])
          AND r.to_entity_id = ANY(:node_ids::uuid[])
          AND r.valid_from <= NOW()
          AND (r.valid_until IS NULL OR r.valid_until > NOW())
        LIMIT :elimit
    """), {
        "node_ids": list(node_ids),
        "elimit": limit * 3,
    })).fetchall()

    nodes = [
        {
            "id": str(r.id),
            "name": r.name,
            "entity_type": r.entity_type or "unknown",
            "relation_count": int(r.relation_count or 0),
            "memory_count": int(r.memory_count or 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in node_rows
    ]

    edges = [
        {
            "id": str(r.id),
            "from": str(r.from_entity_id),
            "to": str(r.to_entity_id),
            "relation_type": r.relation_type,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            "valid_until": r.valid_until.isoformat() if r.valid_until else None,
            "memory_id": str(r.memory_id) if r.memory_id else None,
        }
        for r in edge_rows
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "agent_id": agent_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
