"""Raw session archive routes — sessions, messages, provenance-friendly endings."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.peer import get_or_create
from app.db import get_db
from app.memory.ingest import save_memory
from app.models.api import (
    MemorySaveRequest,
    SessionAppendRequest,
    SessionAppendResponse,
    SessionDetailResponse,
    SessionEndRequest,
    SessionEndResponse,
    SessionListItem,
    SessionMessageItem,
    SessionStartRequest,
    SessionStartResponse,
    MemorySourceLinkRequest,
    MemorySourceLinkResponse,
)

router = APIRouter()


def _estimate_tokens(content: str) -> int:
    return max(1, len(content) // 4) if content else 0


@router.post("/start", response_model=SessionStartResponse)
async def start_session(body: SessionStartRequest, db: AsyncSession = Depends(get_db)):
    agent = await get_or_create(db, body.agent_id)
    agent_uuid = agent["id"] if isinstance(agent, dict) else str(agent.id)
    sid = uuid.uuid4()
    result = await db.execute(text("""
        INSERT INTO sessions (id, agent_id, agent_name, started_at, project_key, title, metadata)
        VALUES (:id, CAST(:agent_id AS uuid), :agent_name, NOW(), :project_key, :title, CAST(:metadata AS jsonb))
        RETURNING started_at
    """), {
        "id": sid,
        "agent_id": agent_uuid,
        "agent_name": body.agent_id,
        "project_key": body.project_key,
        "title": body.title,
        "metadata": json.dumps(body.metadata),
    })
    started_at = result.scalar()
    await db.execute(text("""
        UPDATE agents SET session_count = session_count + 1, last_active = NOW()
        WHERE id = CAST(:agent_id AS uuid)
    """), {"agent_id": agent_uuid})
    await db.commit()
    return SessionStartResponse(session_id=str(sid), agent_id=body.agent_id, started_at=started_at)


@router.post("/{session_id}/messages", response_model=SessionAppendResponse)
async def append_message(
    session_id: str,
    body: SessionAppendRequest,
    db: AsyncSession = Depends(get_db),
):
    exists = (await db.execute(text("SELECT id FROM sessions WHERE id = CAST(:id AS uuid)"), {"id": session_id})).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found")
    mid = uuid.uuid4()
    token_estimate = body.token_estimate if body.token_estimate is not None else _estimate_tokens(body.content)
    await db.execute(text("""
        INSERT INTO messages (id, session_id, role, content, token_estimate, created_at, metadata)
        VALUES (:id, CAST(:session_id AS uuid), :role, :content, :token_estimate, NOW(), CAST(:metadata AS jsonb))
    """), {
        "id": mid,
        "session_id": session_id,
        "role": body.role,
        "content": body.content,
        "token_estimate": token_estimate,
        "metadata": json.dumps(body.metadata),
    })
    await db.commit()
    return SessionAppendResponse(message_id=str(mid), session_id=session_id, token_estimate=token_estimate)


@router.post("/{session_id}/end", response_model=SessionEndResponse)
async def end_session(
    session_id: str,
    body: SessionEndRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(text("""
        SELECT id, agent_name, metadata
        FROM sessions
        WHERE id = CAST(:id AS uuid)
    """), {"id": session_id})).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    metadata = dict(row.metadata or {}) | dict(body.metadata or {})
    await db.execute(text("""
        UPDATE sessions
        SET ended_at = COALESCE(ended_at, NOW()), metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:metadata AS jsonb)
        WHERE id = CAST(:id AS uuid)
    """), {"id": session_id, "metadata": json.dumps(metadata)})
    await db.commit()

    memory_id = None
    if body.durable and body.summary and body.summary.strip():
        saved = await save_memory(db, request.app.state.redis, MemorySaveRequest(
            content=body.summary.strip(),
            agent_id=row.agent_name,
            memory_type="experience",
            importance=0.75,
            tags=["session-summary"],
            metadata={"source": "session", "session_id": session_id},
        ))
        memory_id = saved.id
        await db.execute(text("""
            INSERT INTO memory_sources (memory_id, source_kind, source_id, metadata)
            VALUES (CAST(:memory_id AS uuid), 'session', CAST(:source_id AS uuid), CAST(:metadata AS jsonb))
            ON CONFLICT DO NOTHING
        """), {"memory_id": memory_id, "source_id": session_id, "metadata": json.dumps({"summary": True})})
        await db.commit()

    return SessionEndResponse(session_id=session_id, ended=True, memory_id=memory_id)


@router.get("", response_model=list[SessionListItem])
async def list_sessions(
    agent_id: str | None = Query(default=None),
    project_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    params: dict = {"limit": limit}
    if agent_id:
        conditions.append("s.agent_name = :agent_id")
        params["agent_id"] = agent_id
    if project_key:
        conditions.append("s.project_key = :project_key")
        params["project_key"] = project_key
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = await db.execute(text(f"""
        SELECT s.id, s.agent_name, s.project_key, s.title, s.started_at, s.ended_at,
               COUNT(m.id) AS message_count
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.started_at DESC
        LIMIT :limit
    """), params)
    return [SessionListItem(
        id=str(r.id), agent_id=r.agent_name, project_key=r.project_key, title=r.title,
        started_at=r.started_at, ended_at=r.ended_at, message_count=r.message_count or 0,
    ) for r in rows.fetchall()]


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, limit: int = Query(default=200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    s = (await db.execute(text("""
        SELECT id, agent_name, project_key, title, started_at, ended_at, metadata
        FROM sessions WHERE id = CAST(:id AS uuid)
    """), {"id": session_id})).fetchone()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    rows = await db.execute(text("""
        SELECT id, role, content, token_estimate, created_at, metadata
        FROM messages
        WHERE session_id = CAST(:id AS uuid)
        ORDER BY created_at ASC
        LIMIT :limit
    """), {"id": session_id, "limit": limit})
    messages = [SessionMessageItem(
        id=str(r.id), role=r.role, content=r.content, token_estimate=r.token_estimate,
        created_at=r.created_at, metadata=dict(r.metadata or {}),
    ) for r in rows.fetchall()]
    return SessionDetailResponse(
        id=str(s.id), agent_id=s.agent_name, project_key=s.project_key, title=s.title,
        started_at=s.started_at, ended_at=s.ended_at, metadata=dict(s.metadata or {}), messages=messages,
    )


@router.post("/sources/link", response_model=MemorySourceLinkResponse)
async def link_memory_source(body: MemorySourceLinkRequest, db: AsyncSession = Depends(get_db)):
    """Link a distilled memory to a raw session/message/event source."""
    await db.execute(text("""
        INSERT INTO memory_sources (memory_id, source_kind, source_id, metadata)
        VALUES (CAST(:memory_id AS uuid), :source_kind, CAST(:source_id AS uuid), CAST(:metadata AS jsonb))
        ON CONFLICT DO NOTHING
    """), {
        "memory_id": body.memory_id,
        "source_kind": body.source_kind,
        "source_id": body.source_id,
        "metadata": json.dumps(body.metadata),
    })
    await db.commit()
    return MemorySourceLinkResponse(linked=True)