"""Compatibility aliases for Hindsight, Honcho, BrainSync, and AgentMemory-style clients."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import get_context
from app.agents.peer import get_or_create
from app.db import get_db
from app.memory.ingest import save_memory
from app.memory.reflect import reflect as do_reflect
from app.models.api import MemoryRecallRequest, MemoryReflectRequest, MemorySaveRequest
from app.routers.memory import recall as nexus_recall

router = APIRouter()


@router.post("/retain")
async def hindsight_retain(body: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Hindsight-style retain alias for Nexus memory save."""
    content = body.get("content") or body.get("text") or body.get("memory") or ""
    req = MemorySaveRequest(
        content=content,
        agent_id=body.get("agent_id") or body.get("peer_id") or body.get("workspace_id") or "default",
        memory_type=body.get("memory_type") or body.get("type") or "observation",
        importance=float(body.get("importance", 0.6)),
        tags=list(body.get("tags") or []),
        metadata=dict(body.get("metadata") or {}) | {"compat": "hindsight-retain"},
    )
    saved = await save_memory(db, request.app.state.redis, req)
    return {"retained": True, "id": saved.id, "classified_type": saved.classified_type, "deduplicated": saved.deduplicated}


@router.post("/recall")
async def hindsight_recall(body: dict):
    """Hindsight-style recall alias for Nexus four-way recall."""
    req = MemoryRecallRequest(
        query=body.get("query") or body.get("text") or "",
        agent_id=body.get("agent_id") or body.get("peer_id") or body.get("workspace_id"),
        limit=int(body.get("limit", 10)),
        memory_types=body.get("memory_types") or body.get("types"),
        search_modes=body.get("search_modes") or body.get("modes"),
    )
    result = await nexus_recall(req)
    return result.model_dump(mode="json")


@router.post("/reflect")
async def hindsight_reflect(body: dict, db: AsyncSession = Depends(get_db)):
    """Hindsight-style reflect alias for Nexus synthesis."""
    req = MemoryReflectRequest(
        query=body.get("query") or body.get("text") or "",
        agent_id=body.get("agent_id") or body.get("peer_id") or body.get("workspace_id"),
        context=body.get("context"),
        depth=body.get("depth", "mid"),
    )
    result = await do_reflect(db, req)
    return result.model_dump(mode="json")


@router.get("/workspaces/{workspace_id}/peers/{peer_id}/context")
async def honcho_peer_context(
    workspace_id: str,
    peer_id: str,
    tokens: int = 2000,
    db: AsyncSession = Depends(get_db),
):
    """Honcho-style workspace peer context alias."""
    agent_id = f"{workspace_id}:{peer_id}"
    await get_or_create(db, agent_id)
    return await get_context(db, agent_id, token_budget=tokens)


@router.get("/workspaces/{workspace_id}/peers/{peer_id}/card")
async def honcho_peer_card(workspace_id: str, peer_id: str):
    """Hint clients to use the canonical agent card endpoint for peer cards."""
    return {
        "workspace_id": workspace_id,
        "peer_id": peer_id,
        "agent_id": f"{workspace_id}:{peer_id}",
        "canonical": f"/v1/agents/{workspace_id}:{peer_id}/card",
    }


@router.get("/agentmemory/health")
async def agentmemory_health_alias():
    """AgentMemory-style basic health/discovery alias."""
    return {
        "ok": True,
        "service": "nexus",
        "compatibility": ["hindsight", "honcho", "brainsync", "agentmemory"],
        "mcp": "/mcp",
        "openapi": "/.well-known/nexus/openapi.json",
    }
