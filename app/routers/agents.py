"""Agent routes — context, learning, knowledge graph."""

import uuid
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from pydantic import BaseModel, Field
from app.models.api import AgentLearnRequest, MemorySaveRequest, MemorySaveResponse, AgentContextResponse, AgentTransferResponse, AgentCardResponse, MemoryResult


class EntityItem(BaseModel):
    name: str
    entityType: str = ""

class EntitiesRequest(BaseModel):
    entities: list[EntityItem] = Field(default_factory=list)

class RelationItem(BaseModel):
    from_: str = Field(alias="from")
    to: str
    relationType: str = ""
    model_config = {"populate_by_name": True}

class RelationsRequest(BaseModel):
    relations: list[RelationItem] = Field(default_factory=list)

class AgentUpdateRequest(BaseModel):
    """Update agent metadata for registry enhancement."""
    model: Optional[str] = None
    capabilities: Optional[list[str]] = None
    last_active: Optional[datetime] = None

from app.agents.peer import get_or_create
from app.agents.context import get_context
from app.memory.ingest import save_memory

router = APIRouter()


@router.get("/{agent_id}/context", response_model=AgentContextResponse)
async def agent_context(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tokens: int = Query(default=2000, ge=100, le=16000),
    search_query: Optional[str] = Query(default=None),
):
    await get_or_create(db, agent_id)
    return await get_context(db, agent_id, token_budget=tokens, search_query=search_query)


@router.get("/{agent_id}/card", response_model=AgentCardResponse)
async def agent_card(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Honcho-style peer/agent card with profile, confidence, stats, and sources."""
    await get_or_create(db, agent_id)

    agent_row = (await db.execute(text("""
        SELECT id, name, model, last_active, session_count, metadata, representation
        FROM agents
        WHERE name = :agent_id
    """), {"agent_id": agent_id})).fetchone()
    if not agent_row:
        return AgentCardResponse(agent_id=agent_id, display_name=agent_id)

    stats = (await db.execute(text("""
        SELECT COUNT(*) AS memory_count,
               COALESCE(AVG(m.importance), 0) AS avg_importance,
               COALESCE(SUM(m.confirmed_count), 0) AS confirmed_count,
               COALESCE(SUM(m.contradicted_count), 0) AS contradicted_count
        FROM memories m
        WHERE m.agent_id = :aid
    """), {"aid": agent_row.id})).fetchone()

    entity_count = (await db.execute(text("SELECT COUNT(*) FROM entities WHERE agent_id = :aid"), {"aid": agent_row.id})).scalar() or 0
    conclusion_count = (await db.execute(text("SELECT COUNT(*) FROM conclusions WHERE agent_id = :aid"), {"aid": agent_row.id})).scalar() or 0
    summary_count = (await db.execute(text("SELECT COUNT(*) FROM summaries WHERE agent_id = :aid"), {"aid": agent_row.id})).scalar() or 0

    type_rows = await db.execute(text("""
        SELECT memory_type, COUNT(*) AS count
        FROM memories
        WHERE agent_id = :aid
        GROUP BY memory_type
        ORDER BY count DESC
    """), {"aid": agent_row.id})
    top_memory_types = {r.memory_type: int(r.count) for r in type_rows.fetchall()}

    source_rows = await db.execute(text("""
        SELECT ms.source_kind, COUNT(*) AS count
        FROM memory_sources ms
        JOIN memories m ON m.id = ms.memory_id
        WHERE m.agent_id = :aid
        GROUP BY ms.source_kind
        ORDER BY count DESC
    """), {"aid": agent_row.id})
    source_counts = {r.source_kind: int(r.count) for r in source_rows.fetchall()}

    conclusion_rows = await db.execute(text("""
        SELECT content FROM conclusions
        WHERE agent_id = :aid
        ORDER BY created_at DESC
        LIMIT 8
    """), {"aid": agent_row.id})
    conclusions = [r.content for r in conclusion_rows.fetchall()]

    memory_rows = await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance, m.access_count,
               m.confirmed_count, m.contradicted_count, m.created_at, m.metadata,
               a.name AS agent_name
        FROM memories m
        LEFT JOIN agents a ON a.id = m.agent_id
        WHERE m.agent_id = :aid
        ORDER BY m.importance DESC, m.created_at DESC
        LIMIT 8
    """), {"aid": agent_row.id})
    recent_memories = [MemoryResult(
        id=str(r.id), content=r.content, score=float(r.importance or 0.0),
        memory_type=r.memory_type, agent_id=str(agent_row.id), agent_name=r.agent_name,
        importance=float(r.importance or 0.0), access_count=r.access_count or 0,
        confirmed_count=r.confirmed_count or 0, contradicted_count=r.contradicted_count or 0,
        created_at=r.created_at, metadata=dict(r.metadata or {}), matched_by=["agent-card"],
    ) for r in memory_rows.fetchall()]

    metadata = dict(agent_row.metadata or {})
    memory_count = int(stats.memory_count or 0)
    confirmed = int(stats.confirmed_count or 0)
    contradicted = int(stats.contradicted_count or 0)
    # Confidence combines evidence volume, representation, confirmations, and contradiction penalty.
    volume_score = min(0.45, memory_count / 100 * 0.45)
    representation_score = 0.2 if agent_row.representation else 0.0
    conclusion_score = min(0.15, conclusion_count / 10 * 0.15)
    trust_score = min(0.2, confirmed / max(memory_count, 1) * 0.2) - min(0.25, contradicted / max(memory_count, 1) * 0.25)
    confidence = round(max(0.0, min(1.0, volume_score + representation_score + conclusion_score + trust_score)), 3)

    return AgentCardResponse(
        agent_id=agent_id,
        display_name=metadata.get("display_name") or agent_row.name,
        model=agent_row.model,
        last_active=agent_row.last_active,
        session_count=agent_row.session_count or 0,
        memory_count=memory_count,
        entity_count=int(entity_count),
        conclusion_count=int(conclusion_count),
        summary_count=int(summary_count),
        confirmed_count=confirmed,
        contradicted_count=contradicted,
        avg_importance=float(stats.avg_importance or 0.0),
        top_memory_types=top_memory_types,
        capabilities=list(metadata.get("capabilities") or []),
        representation=agent_row.representation,
        recent_memories=recent_memories,
        conclusions=conclusions,
        source_counts=source_counts,
        confidence=confidence,
        metadata=metadata,
    )


@router.post("/{agent_id}/learn", response_model=MemorySaveResponse)
async def agent_learn(
    agent_id: str,
    body: AgentLearnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    req = MemorySaveRequest(
        content=body.content,
        agent_id=agent_id,
        memory_type=body.memory_type,
        importance=body.importance,
        metadata=body.metadata,
        tags=body.tags,
    )
    return await save_memory(db, request.app.state.redis, req)


@router.post("/{from_agent}/transfer/{to_agent}", response_model=AgentTransferResponse)
async def transfer_agent_knowledge(
    from_agent: str,
    to_agent: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Copy recent high-value memories from one agent to another."""
    await get_or_create(db, from_agent)
    await get_or_create(db, to_agent)

    rows = await db.execute(text("""
        SELECT m.content, m.memory_type, m.importance, m.metadata
        FROM memories m
        JOIN agents a ON a.id = m.agent_id
        WHERE a.name = :from_agent
        ORDER BY m.importance DESC, m.created_at DESC
        LIMIT :limit
    """), {"from_agent": from_agent, "limit": limit})

    transferred_ids: list[str] = []
    for row in rows.fetchall():
        metadata = dict(row.metadata or {})
        tags = list(metadata.get("tags") or [])
        if "transferred" not in tags:
            tags.append("transferred")
        metadata.update({"transferred_from": from_agent, "tags": tags})
        req = MemorySaveRequest(
            content=row.content,
            agent_id=to_agent,
            memory_type=row.memory_type,
            importance=min(1.0, float(row.importance or 0.5) + 0.05),
            metadata=metadata,
            tags=tags,
        )
        saved = await save_memory(db, request.app.state.redis, req)
        transferred_ids.append(saved.id)

    return AgentTransferResponse(
        from_agent=from_agent,
        to_agent=to_agent,
        transferred=len(transferred_ids),
        memory_ids=transferred_ids,
    )


@router.post("/{agent_id}/entities")
async def upsert_entities(agent_id: str, body: EntitiesRequest, db: AsyncSession = Depends(get_db)):
    """Create knowledge graph entities (skips existing names)."""
    await get_or_create(db, agent_id)
    agent_row = await db.execute(text("SELECT id FROM agents WHERE name = :n"), {"n": agent_id})
    aid = agent_row.scalar()
    created = []
    for ent in body.entities:
        name = ent.name.strip()
        if not name:
            continue
        result = await db.execute(text("""
            INSERT INTO entities (name, entity_type, agent_id)
            VALUES (:name, :etype, :aid)
            ON CONFLICT DO NOTHING
            RETURNING id
        """), {"name": name, "etype": ent.entityType, "aid": aid})
        row = result.fetchone()
        if row:
            created.append({"name": name, "id": str(row.id)})
    await db.commit()
    return {"created": len(created), "entities": created}


@router.post("/{agent_id}/relations")
async def upsert_relations(agent_id: str, body: RelationsRequest, db: AsyncSession = Depends(get_db)):
    """Create knowledge graph relations (skips duplicates)."""
    await get_or_create(db, agent_id)
    agent_row = await db.execute(text("SELECT id FROM agents WHERE name = :n"), {"n": agent_id})
    aid = agent_row.scalar()
    created = 0
    for rel in body.relations:
        frm = rel.from_.strip()
        to = rel.to.strip()
        rtype = rel.relationType.strip()
        if not (frm and to and rtype):
            continue
        # Ensure both entities exist
        for ename in (frm, to):
            await db.execute(text("""
                INSERT INTO entities (name, entity_type, agent_id)
                VALUES (:name, 'unknown', :aid)
                ON CONFLICT DO NOTHING
            """), {"name": ename, "aid": aid})
        fe = await db.execute(text("SELECT id FROM entities WHERE name = :n AND agent_id = :aid"), {"n": frm, "aid": aid})
        te = await db.execute(text("SELECT id FROM entities WHERE name = :n AND agent_id = :aid"), {"n": to, "aid": aid})
        fid = fe.scalar()
        tid = te.scalar()
        if fid and tid:
            await db.execute(text("""
                INSERT INTO relations (from_entity_id, to_entity_id, relation_type)
                VALUES (:fid, :tid, :rtype)
                ON CONFLICT DO NOTHING
            """), {"fid": fid, "tid": tid, "rtype": rtype})
            created += 1
    await db.commit()
    return {"created": created}


@router.get("/{agent_id}/entities")
async def get_entities(agent_id: str, names: str = Query(default=""), db: AsyncSession = Depends(get_db)):
    """Retrieve entities by name list (comma-separated)."""
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        rows = await db.execute(text("""
            SELECT e.name, e.entity_type,
                   array_agg(DISTINCT r.relation_type || '->' || te.name) FILTER (WHERE te.name IS NOT NULL) as relations
            FROM entities e
            JOIN agents a ON a.id = e.agent_id AND a.name = :agent_id
            LEFT JOIN relations r ON r.from_entity_id = e.id
            LEFT JOIN entities te ON te.id = r.to_entity_id
            GROUP BY e.name, e.entity_type
            LIMIT 100
        """), {"agent_id": agent_id})
    else:
        rows = await db.execute(text("""
            SELECT e.name, e.entity_type,
                   array_agg(DISTINCT r.relation_type || '->' || te.name) FILTER (WHERE te.name IS NOT NULL) as relations
            FROM entities e
            JOIN agents a ON a.id = e.agent_id AND a.name = :agent_id
            LEFT JOIN relations r ON r.from_entity_id = e.id
            LEFT JOIN entities te ON te.id = r.to_entity_id
            WHERE e.name = ANY(:names)
            GROUP BY e.name, e.entity_type
        """), {"agent_id": agent_id, "names": name_list})
    result = []
    for row in rows.fetchall():
        result.append({
            "name": row.name,
            "entityType": row.entity_type,
            "relations": [r for r in (row.relations or []) if r],
        })
    return {"entities": result}


@router.get("/{agent_id}/blast-radius")
async def blast_radius(
    agent_id: str,
    files: str = Query(default=""),
    max_depth: int = Query(default=2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
):
    """Find all entities impacted by changed files via BFS relation traversal."""
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    if not file_list:
        return {"impacted": [], "depth": 0}
    # Seed: entities whose name matches any changed file (by path component)
    seeds = []
    for fname in file_list:
        basename = fname.split("/")[-1]
        rows = await db.execute(text("""
            SELECT e.id, e.name FROM entities e
            JOIN agents a ON a.id = e.agent_id AND a.name = :agent_id
            WHERE e.name ILIKE :pat OR e.name ILIKE :base
        """), {"agent_id": agent_id, "pat": f"%{fname}%", "base": f"%{basename}%"})
        seeds.extend(rows.fetchall())

    visited = {str(r.id): r.name for r in seeds}
    frontier = list(visited.keys())
    depth = 0
    while frontier and depth < max_depth:
        rows = await db.execute(text("""
            SELECT DISTINCT e.id::text, e.name, r.relation_type
            FROM relations r
            JOIN entities e ON e.id = r.to_entity_id
            WHERE r.from_entity_id = ANY(CAST(:frontier AS uuid[]))
            AND r.to_entity_id != ALL(CAST(:visited AS uuid[]))
        """), {"frontier": frontier, "visited": list(visited.keys())})
        new_frontier = []
        for row in rows.fetchall():
            if row.id not in visited:
                visited[row.id] = row.name
                new_frontier.append(row.id)
        frontier = new_frontier
        depth += 1

    return {
        "changed_files": file_list,
        "impacted": [{"id": k, "name": v} for k, v in visited.items()],
        "depth_reached": depth,
    }


@router.post("/{agent_id}/update")
async def update_agent_metadata(
    agent_id: str,
    body: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update agent registry fields (model, capabilities, last_active) and increment session count."""
    await get_or_create(db, agent_id)
    
    updates = []
    params = {"agent_id": agent_id}
    
    if body.model is not None:
        updates.append("model = :model")
        params["model"] = body.model
    
    if body.capabilities is not None:
        updates.append("metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('capabilities', :capabilities)")
        params["capabilities"] = body.capabilities
    
    if body.last_active is not None:
        updates.append("last_active = :last_active")
        params["last_active"] = body.last_active
    else:
        # Auto-update last_active if not provided
        updates.append("last_active = NOW()")
    
    # Always increment session count on update
    updates.append("session_count = session_count + 1")
    
    if updates:
        query = f"""
            UPDATE agents 
            SET {', '.join(updates)}
            WHERE name = :agent_id
            RETURNING id, name, model, session_count, last_active, metadata
        """
        result = await db.execute(text(query), params)
        await db.commit()
        row = result.fetchone()
        if row:
            return {
                "id": str(row.id),
                "name": row.name,
                "model": row.model,
                "session_count": row.session_count,
                "last_active": row.last_active.isoformat() if row.last_active else None,
                "metadata": row.metadata or {},
            }
    
    return {"success": False, "message": "Agent not found"}


@router.get("/discover")
async def discover_agents(
    model: Optional[str] = Query(default=None),
    active_within_hours: int = Query(default=24, ge=1, le=720),
    min_sessions: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Discover agents by model, recent activity, and session count for multi-agent architectures."""
    
    conditions = []
    params = {"hours": active_within_hours, "min_sessions": min_sessions}
    
    # Filter by recent activity
    conditions.append("last_active > NOW() - (INTERVAL '1 hour' * :hours)")
    
    # Filter by minimum session count
    if min_sessions > 0:
        conditions.append("session_count >= :min_sessions")
    
    # Filter by model if specified
    if model:
        conditions.append("model = :model")
        params["model"] = model
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    query = f"""
        SELECT id, name, model, session_count, last_active, metadata, created_at
        FROM agents
        {where_clause}
        ORDER BY last_active DESC, session_count DESC
        LIMIT 50
    """
    
    result = await db.execute(text(query), params)
    agents = []
    for row in result.fetchall():
        metadata = dict(row.metadata or {})
        agents.append({
            "id": str(row.id),
            "name": row.name,
            "model": row.model,
            "session_count": row.session_count,
            "last_active": row.last_active.isoformat() if row.last_active else None,
            "capabilities": metadata.get("capabilities", []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "metadata": metadata,
        })
    
    return {
        "agents": agents,
        "total": len(agents),
        "filters": {
            "model": model,
            "active_within_hours": active_within_hours,
            "min_sessions": min_sessions,
        }
    }
