"""Nexus sys_core router — search, save, sync, bridge-proxy, task-state endpoints."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.integrations import sys_bridge as bs
from app.memory.ingest import save_memory
from app.models.api import MemorySaveRequest
from app.db import SessionLocal

log = logging.getLogger("nexus.routers.sys_bridge")
router = APIRouter()


class NexusSearchRequest(BaseModel):
    query: str
    project: str = "development1"
    limit: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="semantic", description="semantic | fulltext | both")


class NexusSaveRequest(BaseModel):
    title: str
    content: str
    project: str = "development1"
    category: str = "how-it-works"


class NexusSyncRequest(BaseModel):
    project: str = "development1"
    agent_id: str = "default"
    limit: int = Field(default=100, ge=1, le=500)


@router.get("/health")
async def nexus_sys_health():
    return await bs.health()


@router.post("/search")
async def nexus_search(body: NexusSearchRequest):
    try:
        if body.mode == "fulltext":
            results = await bs.fulltext_search(body.query, body.project, body.limit)
        elif body.mode == "both":
            sem, lex = await __import__("asyncio").gather(
                bs.search(body.query, body.project, body.limit),
                bs.fulltext_search(body.query, body.project, body.limit),
                return_exceptions=True,
            )
            seen, results = set(), []
            for lst in (sem, lex):
                if isinstance(lst, Exception):
                    continue
                for item in lst:
                    key = item.get("id") or item.get("title") or str(item)
                    if key not in seen:
                        seen.add(key)
                        results.append(item)
        else:
            results = await bs.search(body.query, body.project, body.limit)
        return {"results": results, "total": len(results), "project": body.project}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


@router.post("/save")
async def nexus_save(body: NexusSaveRequest):
    try:
        result = await bs.save(body.title, body.content, body.project, body.category)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


@router.get("/context/{project}")
async def nexus_context(project: str):
    try:
        return await bs.get_context(project)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


@router.get("/gotchas/{project}")
async def nexus_gotchas(project: str):
    try:
        return {"results": await bs.get_gotchas(project), "project": project}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


@router.get("/conventions/{project}")
async def nexus_conventions(project: str):
    try:
        return {"results": await bs.get_conventions(project), "project": project}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


@router.post("/sync")
async def nexus_sync(body: NexusSyncRequest, request: Request):
    """Pull Nexus sys observationservations → Nexus memories for an agent."""
    try:
        observations = await bs.search("", body.project, body.limit)
        if not observations:
            # Fallback: try getting context which includes recent observations
            ctx = await bs.get_context(body.project)
            observations = ctx.get("recent_observations", []) or ctx.get("observations", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")

    saved, skipped = 0, 0
    redis = getattr(request.app.state, "redis", None)

    async with SessionLocal() as db:
        for obs in observations:
            content = obs.get("content") or obs.get("text") or ""
            title = obs.get("title") or ""
            category = obs.get("category") or "how-it-works"
            if not content:
                skipped += 1
                continue
            full_content = f"{title}: {content}" if title and title not in content else content
            try:
                await save_memory(db, redis, MemorySaveRequest(
                    content=full_content[:50_000],
                    agent_id=body.agent_id,
                    memory_type=bs.to_nexus_memory_type(category),
                    importance=min(1.0, float(obs.get("importance", 0.5))),
                    tags=list(obs.get("tags", [])) + ["nexus-sys", f"project:{body.project}"],
                    metadata={"nexus_sys_id": str(obs.get("id", "")), "nexus_sys_project": body.project, "category": category},
                ))
                saved += 1
            except Exception as e:
                log.warning("Failed to sync observation: %s", e)
                skipped += 1

    return {"saved": saved, "skipped": skipped, "project": body.project, "agent_id": body.agent_id}


class BridgeCallRequest(BaseModel):
    project: str = "development1"
    tool: str
    args: dict[str, Any] = {}


@router.post("/bridge")
async def bridge_call(body: BridgeCallRequest):
    """Proxy a raw tool call to the Nexus bridge subprocess (for filesystem tools)."""
    try:
        result = await bs._call(body.tool, body.project, body.args)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nexus bridge error: {e}")


class TaskStateRequest(BaseModel):
    state: str


@router.put("/taskstate/{project}")
async def save_task_state(project: str, body: TaskStateRequest, request: Request):
    """Persist task state/checklist to Redis keyed by project."""
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        raise HTTPException(status_code=503, detail="Redis not available")
    await redis.hset("nexus:taskstate", project, body.state)
    return {"saved": True, "project": project}


@router.get("/taskstate/{project}")
async def get_task_state(project: str, request: Request):
    """Retrieve last saved task state for a project."""
    redis = getattr(request.app.state, "redis", None)
    if not redis:
        raise HTTPException(status_code=503, detail="Redis not available")
    state = await redis.hget("nexus:taskstate", project)
    return {"state": state or "", "project": project}
