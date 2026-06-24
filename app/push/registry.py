"""Adapter registry — maps agent IDs to their push adapters.

Registrations are stored in Redis as JSON so they survive restarts and
can be updated at runtime via the hooks API. A default set of adapters
is also loaded from config for well-known agents (claude-code, hermes, etc).
"""

import json
import logging
import os
from typing import Any

from app.push.adapters.base import PushAdapter
from app.push.adapters.env_file import EnvFileAdapter
from app.push.adapters.file_inject import FileInjectAdapter
from app.push.adapters.webhook import WebhookAdapter

log = logging.getLogger("nexus.push.registry")

_REDIS_KEY = "nexus:push:registry"


def _build_adapter(cfg: dict[str, Any]) -> PushAdapter | None:
    t = cfg.get("type")
    if t == "file_inject":
        return FileInjectAdapter(cfg["path"], cfg.get("mode", "markdown_block"))
    elif t == "webhook":
        return WebhookAdapter(cfg["url"], cfg.get("secret", ""), cfg.get("timeout", 5.0))
    elif t == "env_file":
        return EnvFileAdapter(cfg["path"], cfg.get("var_name", "NEXUS_CONTEXT"))
    else:
        log.warning("Unknown adapter type: %s", t)
        return None


def _default_registrations() -> dict[str, list[dict]]:
    """Built-in registrations for well-known local agents."""
    home = os.path.expanduser("~")
    return {
        "claude-code": [
            {"type": "file_inject", "path": f"{home}/.claude/CLAUDE.md", "mode": "markdown_block"},
        ],
        "hermes": [
            # Hermes auto-injects ~/.hermes/USER.md into every system prompt
            {"type": "file_inject", "path": f"{home}/.hermes/USER.md", "mode": "markdown_block"},
        ],
        "gemini-cli": [
            {"type": "file_inject", "path": f"{home}/.gemini/nexus-context.md", "mode": "markdown_block"},
        ],
        "qwen-cli": [
            {"type": "file_inject", "path": f"{home}/.qwen/nexus-context.md", "mode": "markdown_block"},
        ],
        "openhands": [
            {"type": "env_file", "path": f"{home}/.openhands/nexus.env", "var_name": "NEXUS_CONTEXT"},
        ],
        "swe-agent": [
            {"type": "env_file", "path": f"{home}/.sweagent/nexus.env", "var_name": "NEXUS_CONTEXT"},
        ],
    }


async def get_adapters(redis, agent_id: str) -> list[PushAdapter]:
    """Return all push adapters registered for an agent."""
    adapters: list[PushAdapter] = []

    # Load defaults
    defaults = _default_registrations()
    if agent_id in defaults:
        for cfg in defaults[agent_id]:
            a = _build_adapter(cfg)
            if a:
                adapters.append(a)

    # Load runtime registrations from Redis
    try:
        raw = await redis.hget(_REDIS_KEY, agent_id)
        if raw:
            for cfg in json.loads(raw):
                a = _build_adapter(cfg)
                if a:
                    adapters.append(a)
    except Exception as e:
        log.warning("Failed to load push registry from Redis: %s", e)

    return adapters


async def register_adapter(redis, agent_id: str, cfg: dict[str, Any]) -> None:
    """Add or replace an adapter registration for an agent (persisted to Redis)."""
    try:
        raw = await redis.hget(_REDIS_KEY, agent_id)
        existing: list[dict] = json.loads(raw) if raw else []
        # Replace if same type+path/url
        key = cfg.get("path") or cfg.get("url", "")
        existing = [e for e in existing if (e.get("path") or e.get("url", "")) != key]
        existing.append(cfg)
        await redis.hset(_REDIS_KEY, agent_id, json.dumps(existing))
    except Exception as e:
        log.error("Failed to register adapter: %s", e)


async def unregister_adapter(redis, agent_id: str, path_or_url: str) -> None:
    """Remove an adapter registration for an agent."""
    try:
        raw = await redis.hget(_REDIS_KEY, agent_id)
        if not raw:
            return
        existing = json.loads(raw)
        existing = [e for e in existing if (e.get("path") or e.get("url", "")) != path_or_url]
        await redis.hset(_REDIS_KEY, agent_id, json.dumps(existing))
    except Exception as e:
        log.error("Failed to unregister adapter: %s", e)


async def list_registrations(redis) -> dict[str, list[dict]]:
    """Return all runtime registrations."""
    try:
        all_entries = await redis.hgetall(_REDIS_KEY)
        return {k: json.loads(v) for k, v in all_entries.items()}
    except Exception:
        return {}
