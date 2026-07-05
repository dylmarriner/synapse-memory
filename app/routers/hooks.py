"""Hooks API — register/unregister push adapters at runtime.

Agents or their host processes call these endpoints to tell Nexus where
to deliver active context updates.

POST /v1/hooks/register   — register a webhook or file adapter
DELETE /v1/hooks/unregister — remove an adapter
GET  /v1/hooks            — list all registrations
POST /v1/hooks/trigger    — manually trigger a push for an agent
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.push.daemon import publish_push_event
from app.push.registry import (
    list_registrations,
    register_adapter,
    unregister_adapter,
)

log = logging.getLogger("nexus.routers.hooks")
router = APIRouter()


class AdapterRegistration(BaseModel):
    agent_id: str
    type: Literal["file_inject", "webhook", "env_file"]
    # file_inject / env_file
    path: str | None = None
    mode: str = "markdown_block"
    var_name: str = "NEXUS_CONTEXT"
    # webhook
    url: str | None = None
    secret: str = ""
    timeout: float = 5.0

    def to_cfg(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {"type": self.type}
        if self.type in ("file_inject", "env_file"):
            if not self.path:
                raise ValueError("path required for file_inject / env_file adapters")
            cfg["path"] = self.path
            if self.type == "file_inject":
                cfg["mode"] = self.mode
            else:
                cfg["var_name"] = self.var_name
        elif self.type == "webhook":
            if not self.url:
                raise ValueError("url required for webhook adapter")
            cfg["url"] = self.url
            cfg["secret"] = self.secret
            cfg["timeout"] = self.timeout
        return cfg


class UnregisterRequest(BaseModel):
    agent_id: str
    path_or_url: str


class TriggerRequest(BaseModel):
    agent_id: str
    event: str = "manual_trigger"


@router.post("/register")
async def register_hook(body: AdapterRegistration, request: Request):
    try:
        cfg = body.to_cfg()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await register_adapter(request.app.state.redis, body.agent_id, cfg)
    return {"registered": True, "agent_id": body.agent_id, "type": body.type}


@router.delete("/unregister")
async def unregister_hook(body: UnregisterRequest, request: Request):
    await unregister_adapter(request.app.state.redis, body.agent_id, body.path_or_url)
    return {"unregistered": True}


@router.get("")
async def list_hooks(request: Request):
    return await list_registrations(request.app.state.redis)


@router.post("/trigger")
async def trigger_push(body: TriggerRequest, request: Request):
    """Manually trigger a context push for an agent."""
    await publish_push_event(request.app.state.redis, body.agent_id, body.event)
    return {"triggered": True, "agent_id": body.agent_id}
