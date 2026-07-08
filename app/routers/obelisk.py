"""Obelisk integration routes — command telemetry and optional durable lessons."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import broadcaster
from app.db import get_db
from app.memory.ingest import save_memory
from app.models.api import MemorySaveRequest, ObeliskCommandEventRequest, ObeliskCommandEventResponse

log = logging.getLogger("nexus.routers.obelisk")
router = APIRouter()


def _command_label(command: str) -> str:
    """Return anonymized first words for UI/metrics without full arguments."""
    parts = command.strip().split()
    return " ".join(parts[:3]) if parts else "unknown"


@router.post("/events", response_model=ObeliskCommandEventResponse)
async def record_obelisk_event(
    body: ObeliskCommandEventRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ObeliskCommandEventResponse:
    """Record an Obelisk-wrapped command event.

    By default this stores only compact telemetry in the `events` table and emits
    an SSE event. It does not store raw command output. If `durable=true` and a
    summary is provided, the summary is saved as a normal Nexus memory.
    """
    detail = {
        "kind": "obelisk.command",
        "agent_id": body.agent_id,
        "command_label": _command_label(body.command),
        "exit_code": body.exit_code,
        "duration_ms": body.duration_ms,
        "cwd": body.cwd,
        "output_chars": body.output_chars,
        "filtered_chars": body.filtered_chars,
        "tokens_saved_estimate": body.tokens_saved_estimate,
        "durable": body.durable,
        "tags": sorted(set(["obelisk", *body.tags])),
        "metadata": body.metadata,
    }

    result = await db.execute(text("""
        INSERT INTO events (project_key, actor, action, detail)
        VALUES (:project_key, :actor, 'obelisk.command', :detail)
        RETURNING id
    """), {
        "project_key": str(body.metadata.get("project") or body.cwd or "default")[:200],
        "actor": body.agent_id,
        "detail": json.dumps(detail),
    })
    event_id = str(result.scalar())
    await db.commit()

    memory_id = None
    saved_memory = False
    if body.durable and body.summary and body.summary.strip():
        tags = sorted(set(["obelisk", "command-event", *body.tags]))
        req = MemorySaveRequest(
            content=body.summary.strip(),
            agent_id=body.agent_id,
            memory_type=body.memory_type or ("lesson" if body.exit_code != 0 else "experience"),
            importance=body.importance,
            tags=tags,
            metadata={
                **body.metadata,
                "source": "obelisk",
                "obelisk_event_id": event_id,
                "command_label": _command_label(body.command),
                "exit_code": body.exit_code,
                "duration_ms": body.duration_ms,
            },
        )
        saved = await save_memory(db, request.app.state.redis, req)
        memory_id = saved.id
        saved_memory = not saved.deduplicated

    await broadcaster.broadcast("obelisk", {
        "id": event_id,
        "agent_id": body.agent_id,
        "command_label": _command_label(body.command),
        "exit_code": body.exit_code,
        "tokens_saved_estimate": body.tokens_saved_estimate,
        "memory_id": memory_id,
    })

    return ObeliskCommandEventResponse(
        recorded=True,
        event_id=event_id,
        memory_id=memory_id,
        saved_memory=saved_memory,
    )