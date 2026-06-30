"""Browse/dashboard API — memory listing, agent listing, stats, delete."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, SessionLocal
from app.models.api import (
    BrowseMemoriesResponse, BrowseMemory,
    AgentsListResponse, AgentSummary,
    StatsResponse, TypeCount,
)

log = logging.getLogger("nexus.browse")
router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    try:
        total_memories = (await db.execute(text("SELECT COUNT(*) FROM memories"))).scalar() or 0
        total_agents = (await db.execute(text("SELECT COUNT(*) FROM agents"))).scalar() or 0
        total_entities = (await db.execute(text("SELECT COUNT(*) FROM entities"))).scalar() or 0
        total_conclusions = (await db.execute(text("SELECT COUNT(*) FROM conclusions"))).scalar() or 0

        type_rows = await db.execute(text(
            "SELECT memory_type, COUNT(*) as cnt FROM memories GROUP BY memory_type ORDER BY cnt DESC"
        ))
        by_type = [TypeCount(memory_type=r.memory_type, count=r.cnt) for r in type_rows.fetchall()]

        return StatsResponse(
            total_memories=total_memories,
            total_agents=total_agents,
            total_entities=total_entities,
            total_conclusions=total_conclusions,
            by_type=by_type,
        )
    except Exception as e:
        log.error("Stats query failed: %s", e)
        return StatsResponse()


@router.get("/memories", response_model=BrowseMemoriesResponse)
async def list_memories(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None),
    agent: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if q:
        conditions.append("(to_tsvector('english', m.content) @@ plainto_tsquery('english', :q) OR LOWER(m.content) LIKE :q_like)")
        params["q"] = q
        params["q_like"] = f"%{q.lower()}%"

    if agent:
        conditions.append("a.name = :agent_name")
        params["agent_name"] = agent

    if type:
        conditions.append("m.memory_type = :mtype")
        params["mtype"] = type

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = text(f"""
        SELECT COUNT(*) FROM memories m
        LEFT JOIN agents a ON m.agent_id = a.id
        {where}
    """)
    total = (await db.execute(count_sql, params)).scalar() or 0

    data_sql = text(f"""
        SELECT m.id, m.content, m.memory_type, m.importance, m.access_count,
               m.confirmed_count, m.contradicted_count, m.created_at, m.metadata,
               a.name AS agent_name
        FROM memories m
        LEFT JOIN agents a ON m.agent_id = a.id
        {where}
        ORDER BY m.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(data_sql, params)).fetchall()

    memories = [
        BrowseMemory(
            id=str(r.id),
            content=r.content,
            memory_type=r.memory_type,
            agent_name=r.agent_name,
            importance=float(r.importance),
            access_count=r.access_count,
            confirmed_count=r.confirmed_count or 0,
            contradicted_count=r.contradicted_count or 0,
            created_at=r.created_at,
            metadata=r.metadata or {},
        )
        for r in rows
    ]

    return BrowseMemoriesResponse(memories=memories, total=total, limit=limit, offset=offset)


@router.get("/agents", response_model=AgentsListResponse)
async def list_agents(db: AsyncSession = Depends(get_db)):
    try:
        rows = await db.execute(text("""
            SELECT
                a.id, a.name, a.representation, a.metadata, a.model AS agent_model, lm.latest_metadata,
                COUNT(DISTINCT m.id) AS memory_count,
                COUNT(DISTINCT e.id) AS entity_count,
                COUNT(DISTINCT c.id) AS conclusion_count,
                MAX(m.created_at) AS last_memory_at,
                COALESCE(a.last_active, GREATEST(MAX(m.created_at), a.created_at)) AS last_active,
                COALESCE(a.session_count, (a.metadata->>'session_count')::int, 0) AS session_count,
                EXISTS(SELECT 1 FROM summaries s WHERE s.agent_id = a.id) AS has_summary
            FROM agents a
            LEFT JOIN memories    m ON m.agent_id = a.id
            LEFT JOIN entities    e ON e.agent_id = a.id
            LEFT JOIN conclusions c ON c.agent_id = a.id
            LEFT JOIN LATERAL (
                SELECT m2.metadata AS latest_metadata
                FROM memories m2
                WHERE m2.agent_id = a.id
                ORDER BY m2.created_at DESC
                LIMIT 1
            ) lm ON TRUE
            GROUP BY a.id, lm.latest_metadata
            ORDER BY memory_count DESC
        """))
        agents = []
        for r in rows.fetchall():
            metadata = dict(r.metadata or {})
            latest_metadata = dict(r.latest_metadata or {})
            device = metadata.get("device") or metadata.get("device_name") or latest_metadata.get("device") or latest_metadata.get("device_name")
            hostname = metadata.get("hostname") or metadata.get("host") or latest_metadata.get("hostname") or latest_metadata.get("host") or latest_metadata.get("machine")
            source = metadata.get("source") or metadata.get("client") or latest_metadata.get("source") or latest_metadata.get("client")
            agents.append(AgentSummary(
                id=str(r.id),
                name=r.name,
                memory_count=r.memory_count or 0,
                entity_count=r.entity_count or 0,
                conclusion_count=r.conclusion_count or 0,
                representation=r.representation,
                capabilities=list(metadata.get("capabilities") or []),
                model=r.agent_model or metadata.get("model") or latest_metadata.get("model"),
                device=device,
                hostname=hostname,
                source=source,
                last_active=r.last_active,
                session_count=r.session_count or 0,
                last_memory_at=r.last_memory_at,
                has_summary=bool(r.has_summary),
            ))
        return AgentsListResponse(agents=agents)
    except Exception as e:
        log.error("Agents list failed: %s", e)
        return AgentsListResponse(agents=[])


@router.post("/agents/{agent_name}/represent")
async def rebuild_representation(agent_name: str):
    """Trigger an LLM representation rebuild for an agent."""
    from app.agents.peer import build_representation
    async with SessionLocal() as db:
        rep = await build_representation(db, agent_name)
    return {"agent": agent_name, "representation": rep, "rebuilt": rep is not None}
