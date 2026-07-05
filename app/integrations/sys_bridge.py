"""Nexus sys_core integration — async client for the Nexus sys bridge.

The bridge (scripts/sys-bridge.mjs) must be running and accessible at
NEXUS_BRIDGE_URL (default: http://sys-bridge:7778).

sys_core category → Nexus memory_type mapping:
  what-changed / discovery  → experience
  problem-fix / gotcha      → lesson
  decision / trade-off      → world
  convention / how-it-works → world
  tool-pattern              → experience
"""

import json
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("nexus.sys_bridge")

BRIDGE_URL = os.environ.get("NEXUS_BRIDGE_URL", "http://sys-bridge:7778")

# sys_core category → Nexus memory_type
CATEGORY_MAP: dict[str, str] = {
    "what-changed":  "experience",
    "discovery":     "experience",
    "problem-fix":   "lesson",
    "gotcha":        "lesson",
    "decision":      "world",
    "trade-off":     "world",
    "convention":    "world",
    "how-it-works":  "world",
    "tool-pattern":  "experience",
}

# Nexus memory_type → sys_core category
MEMORY_TYPE_MAP: dict[str, str] = {
    "world":       "how-it-works",
    "experience":  "what-changed",
    "observation": "discovery",
    "preference":  "convention",
    "lesson":      "problem-fix",
}


async def _call(tool: str, project: str, args: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{BRIDGE_URL}/call",
            json={"project": project, "tool": tool, "args": args},
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Nexus bridge error: {data['error']}")
        return data.get("result", {})


async def health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{BRIDGE_URL}/health")
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def search(query: str, project: str, limit: int = 10) -> list[dict]:
    """Semantic search across a Nexus project."""
    result = await _call("sys_core_01", project, {"query": query, "limit": limit})
    return _normalize_observations(result)


async def fulltext_search(query: str, project: str, limit: int = 10) -> list[dict]:
    """Full-text keyword search across a Nexus project."""
    result = await _call("sys_core_05", project, {"query": query, "limit": limit})
    return _normalize_observations(result)


async def save(
    title: str,
    content: str,
    project: str,
    category: str = "how-it-works",
) -> dict[str, Any]:
    """Save an observation to Nexus with conflict detection."""
    return await _call("sys_core_02", project, {
        "title": title,
        "content": content,
        "category": category,
    })


async def get_context(project: str) -> dict[str, Any]:
    """Get active project context from Nexus."""
    return await _call("sys_core_14", project, {})


async def get_gotchas(project: str) -> list[dict]:
    """Get critical warnings and gotchas for a project."""
    result = await _call("sys_core_08", project, {})
    return _normalize_observations(result)


async def get_conventions(project: str) -> list[dict]:
    """Get architectural decisions and conventions for a project."""
    result = await _call("sys_core_09", project, {})
    return _normalize_observations(result)


async def get_stats(project: str) -> dict[str, Any]:
    """Get observation counts and session analytics."""
    return await _call("sys_core_07", project, {})


def _normalize_observations(raw: Any) -> list[dict]:
    """Normalise varied Nexus response shapes into a flat list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("observations", "results", "items", "gotchas", "conventions", "decisions"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        # Single result shape
        if "title" in raw or "content" in raw:
            return [raw]
    return []


def to_nexus_memory_type(category: str) -> str:
    return CATEGORY_MAP.get(category, "observation")


def to_nexus_category(memory_type: Optional[str]) -> str:
    return MEMORY_TYPE_MAP.get(memory_type or "observation", "how-it-works")
