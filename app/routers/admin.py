"""Admin and health routes."""

import json
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.api import HealthResponse
from app.memory.consolidate import consolidate

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, db: AsyncSession = Depends(get_db)):
    components: dict[str, bool] = {}

    try:
        await db.execute(text("SELECT 1"))
        components["postgres"] = True
    except Exception:
        components["postgres"] = False

    try:
        await request.app.state.redis.ping()
        components["redis"] = True
    except Exception:
        components["redis"] = False

    s = request.app.state.settings
    components["embeddings"] = bool(s.openai_api_key or s.deepseek_api_key or s.anthropic_api_key)
    components["llm"] = bool(s.openai_api_key or s.anthropic_api_key or s.deepseek_api_key)

    return HealthResponse(healthy=components["postgres"], components=components)


@router.post("/admin/consolidate")
async def trigger_consolidate(db: AsyncSession = Depends(get_db)):
    stats = await consolidate(db)
    return {"success": True, "stats": stats}


async def _memory_jsonl(db: AsyncSession, agent_id: str | None = None):
    where = ""
    params = {}
    if agent_id and agent_id != "all":
        where = "WHERE a.name = :agent_id"
        params["agent_id"] = agent_id
    rows = await db.execute(text(f"""
        SELECT m.id, m.content, m.memory_type, m.importance, m.access_count,
               m.confirmed_count, m.contradicted_count, m.created_at, m.accessed_at,
               m.metadata, a.name AS agent_name
        FROM memories m
        LEFT JOIN agents a ON a.id = m.agent_id
        {where}
        ORDER BY a.name NULLS LAST, m.created_at ASC
    """), params)
    for r in rows.fetchall():
        yield json.dumps({
            "id": str(r.id),
            "agent_id": r.agent_name,
            "content": r.content,
            "memory_type": r.memory_type,
            "importance": float(r.importance),
            "access_count": r.access_count,
            "confirmed_count": r.confirmed_count or 0,
            "contradicted_count": r.contradicted_count or 0,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "accessed_at": r.accessed_at.isoformat() if r.accessed_at else None,
            "metadata": r.metadata or {},
        }, default=str) + "\n"


@router.post("/admin/import")
async def import_backup(items: list[dict] = Body(...), db: AsyncSession = Depends(get_db)):
    imported = 0
    from app.memory.ingest import save_memory
    from app.models.api import MemorySaveRequest
    for item in items:
        req = MemorySaveRequest(
            content=str(item.get("content") or ""),
            agent_id=str(item.get("agent_id") or item.get("agent_name") or "default"),
            memory_type=item.get("memory_type") or "observation",
            importance=float(item.get("importance") or 0.5),
            metadata=dict(item.get("metadata") or {}),
            tags=list((item.get("metadata") or {}).get("tags") or item.get("tags") or []),
        )
        if not req.content:
            continue
        await save_memory(db, None, req)
        imported += 1
    return {"success": True, "imported": imported}

@router.get("/admin/export/all")
async def export_all(db: AsyncSession = Depends(get_db)):
    return StreamingResponse(_memory_jsonl(db, None), media_type="application/x-ndjson")


@router.get("/admin/export/{agent_id}")
async def export_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    return StreamingResponse(_memory_jsonl(db, agent_id), media_type="application/x-ndjson")


