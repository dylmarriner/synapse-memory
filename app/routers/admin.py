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


@router.get("/admin/metrics")
async def admin_metrics(request: Request, db: AsyncSession = Depends(get_db)):
    """Dashboard-ready operational metrics across memory, agents, sessions, and RTK."""
    components = {"postgres": False, "redis": False}
    try:
        await db.execute(text("SELECT 1"))
        components["postgres"] = True
    except Exception:
        pass
    try:
        await request.app.state.redis.ping()
        components["redis"] = True
    except Exception:
        pass

    async def scalar(sql: str, params: dict | None = None, default=0):
        try:
            return (await db.execute(text(sql), params or {})).scalar() or default
        except Exception:
            return default

    totals = {
        "agents": int(await scalar("SELECT COUNT(*) FROM agents")),
        "memories": int(await scalar("SELECT COUNT(*) FROM memories")),
        "entities": int(await scalar("SELECT COUNT(*) FROM entities")),
        "relations": int(await scalar("SELECT COUNT(*) FROM relations")),
        "conclusions": int(await scalar("SELECT COUNT(*) FROM conclusions")),
        "summaries": int(await scalar("SELECT COUNT(*) FROM summaries")),
        "sessions": int(await scalar("SELECT COUNT(*) FROM sessions")),
        "messages": int(await scalar("SELECT COUNT(*) FROM messages")),
        "memory_sources": int(await scalar("SELECT COUNT(*) FROM memory_sources")),
        "events": int(await scalar("SELECT COUNT(*) FROM events")),
    }

    last_24h = {
        "memories": int(await scalar("SELECT COUNT(*) FROM memories WHERE created_at > NOW() - INTERVAL '24 hours'")),
        "sessions": int(await scalar("SELECT COUNT(*) FROM sessions WHERE started_at > NOW() - INTERVAL '24 hours'")),
        "messages": int(await scalar("SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '24 hours'")),
        "events": int(await scalar("SELECT COUNT(*) FROM events WHERE created_at > NOW() - INTERVAL '24 hours'")),
        "rtk_events": int(await scalar("SELECT COUNT(*) FROM events WHERE action = 'rtk.command' AND created_at > NOW() - INTERVAL '24 hours'")),
    }

    memory_type_rows = await db.execute(text("""
        SELECT memory_type, COUNT(*) AS count
        FROM memories
        GROUP BY memory_type
        ORDER BY count DESC
    """))
    memory_types = {r.memory_type: int(r.count) for r in memory_type_rows.fetchall()}

    top_agent_rows = await db.execute(text("""
        SELECT a.name, COUNT(m.id) AS memories, COALESCE(MAX(m.created_at), a.created_at) AS last_memory_at,
               a.session_count, a.last_active
        FROM agents a
        LEFT JOIN memories m ON m.agent_id = a.id
        GROUP BY a.id, a.name, a.created_at, a.session_count, a.last_active
        ORDER BY memories DESC, last_memory_at DESC
        LIMIT 10
    """))
    top_agents = [{
        "agent_id": r.name,
        "memories": int(r.memories or 0),
        "session_count": int(r.session_count or 0),
        "last_active": r.last_active.isoformat() if r.last_active else None,
        "last_memory_at": r.last_memory_at.isoformat() if r.last_memory_at else None,
    } for r in top_agent_rows.fetchall()]

    rtk = {
        "total_events": int(await scalar("SELECT COUNT(*) FROM events WHERE action = 'rtk.command'")),
        "failed_24h": int(await scalar("""
            SELECT COUNT(*) FROM events
            WHERE action = 'rtk.command'
              AND created_at > NOW() - INTERVAL '24 hours'
              AND COALESCE((detail::jsonb->>'exit_code')::int, 0) != 0
        """)),
        "tokens_saved_estimate": int(await scalar("""
            SELECT COALESCE(SUM(COALESCE((detail::jsonb->>'tokens_saved_estimate')::int, 0)), 0)
            FROM events WHERE action = 'rtk.command'
        """)),
        "durable_memories": int(await scalar("SELECT COUNT(*) FROM memories WHERE metadata->>'source' = 'rtk'")),
    }

    recent_rows = await db.execute(text("""
        SELECT id, actor, action, detail, created_at
        FROM events
        ORDER BY created_at DESC
        LIMIT 20
    """))
    recent_events = []
    for row in recent_rows.fetchall():
        try:
            detail = json.loads(row.detail) if isinstance(row.detail, str) else row.detail
        except Exception:
            detail = {"raw": row.detail}
        recent_events.append({
            "id": str(row.id),
            "actor": row.actor,
            "action": row.action,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "detail": detail,
        })

    return {
        "healthy": components["postgres"],
        "components": components,
        "totals": totals,
        "last_24h": last_24h,
        "memory_types": memory_types,
        "top_agents": top_agents,
        "rtk": rtk,
        "recent_events": recent_events,
    }


@router.get("/admin/rtk")
async def rtk_metrics(db: AsyncSession = Depends(get_db)):
    """Return RTK command telemetry for dashboards and operations views."""
    try:
        total = (await db.execute(text("""
            SELECT COUNT(*) FROM events WHERE action = 'rtk.command'
        """))).scalar() or 0

        recent_24h = (await db.execute(text("""
            SELECT COUNT(*) FROM events
            WHERE action = 'rtk.command' AND created_at > NOW() - INTERVAL '24 hours'
        """))).scalar() or 0

        failed_24h = (await db.execute(text("""
            SELECT COUNT(*) FROM events
            WHERE action = 'rtk.command'
              AND created_at > NOW() - INTERVAL '24 hours'
              AND COALESCE((detail::jsonb->>'exit_code')::int, 0) != 0
        """))).scalar() or 0

        saved_tokens = (await db.execute(text("""
            SELECT COALESCE(SUM(COALESCE((detail::jsonb->>'tokens_saved_estimate')::int, 0)), 0)
            FROM events WHERE action = 'rtk.command'
        """))).scalar() or 0

        durable_memories = (await db.execute(text("""
            SELECT COUNT(*) FROM memories
            WHERE metadata->>'source' = 'rtk'
        """))).scalar() or 0

        by_agent_rows = await db.execute(text("""
            SELECT actor AS agent_id, COUNT(*) AS count
            FROM events
            WHERE action = 'rtk.command'
            GROUP BY actor
            ORDER BY count DESC
            LIMIT 10
        """))

        command_rows = await db.execute(text("""
            SELECT detail::jsonb->>'command_label' AS command_label, COUNT(*) AS count
            FROM events
            WHERE action = 'rtk.command'
            GROUP BY command_label
            ORDER BY count DESC
            LIMIT 10
        """))

        recent_rows = await db.execute(text("""
            SELECT id, actor, created_at, detail
            FROM events
            WHERE action = 'rtk.command'
            ORDER BY created_at DESC
            LIMIT 20
        """))

        recent = []
        for row in recent_rows.fetchall():
            try:
                detail = json.loads(row.detail) if isinstance(row.detail, str) else row.detail
            except Exception:
                detail = {"raw": row.detail}
            recent.append({
                "id": str(row.id),
                "agent_id": row.actor,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "command_label": detail.get("command_label"),
                "exit_code": detail.get("exit_code"),
                "duration_ms": detail.get("duration_ms"),
                "tokens_saved_estimate": detail.get("tokens_saved_estimate", 0),
                "durable": bool(detail.get("durable")),
            })

        return {
            "total_events": total,
            "recent_24h": recent_24h,
            "failed_24h": failed_24h,
            "tokens_saved_estimate": int(saved_tokens),
            "durable_memories": durable_memories,
            "by_agent": [{"agent_id": r.agent_id, "count": r.count} for r in by_agent_rows.fetchall()],
            "top_commands": [{"command_label": r.command_label or "unknown", "count": r.count} for r in command_rows.fetchall()],
            "recent": recent,
        }
    except Exception as e:
        return {
            "total_events": 0,
            "recent_24h": 0,
            "failed_24h": 0,
            "tokens_saved_estimate": 0,
            "durable_memories": 0,
            "by_agent": [],
            "top_commands": [],
            "recent": [],
            "error": str(e),
        }


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


@router.post("/admin/scheduled-consolidation")
async def trigger_scheduled_consolidation():
    """Manually trigger the scheduled daily consolidation."""
    from app.scheduler import run_scheduled_consolidation
    result = await run_scheduled_consolidation()
    return result


@router.get("/admin/consolidation-report")
async def get_consolidation_report():
    """Get the most recent consolidation report."""
    from app.scheduler import get_latest_report
    report = await get_latest_report()
    if report:
        return report
    return {"message": "No consolidation report available yet"}


