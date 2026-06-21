"""Thin synchronous HTTP client for the Nexus REST API."""

import json
import os
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any

NEXUS_URL = os.getenv("NEXUS_URL", "http://100.93.75.87:7777")
NEXUS_SECRET = os.getenv("NEXUS_SECRET", "$NEXUS_SECRET")


def _headers():
    h = {"Content-Type": "application/json"}
    if NEXUS_SECRET:
        h["Authorization"] = f"Bearer {NEXUS_SECRET}"
    return h


def _post(path: str, body: dict, timeout: int = 8) -> Optional[dict]:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", data=data, headers=_headers(), method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _get(path: str, timeout: int = 8) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", headers=_headers(), method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def health() -> bool:
    try:
        d = _get("/health", timeout=3)
        return bool(d and d.get("healthy"))
    except Exception:
        return False


def save_memory(content: str, agent_id: str, memory_type: Optional[str] = None,
                importance: float = 0.5, tags: List[str] = None) -> Optional[dict]:
    return _post("/v1/memory/save", {
        "content": content,
        "agent_id": agent_id,
        "memory_type": memory_type,
        "importance": importance,
        "tags": tags or [],
    })


def recall(query: str, agent_id: Optional[str] = None,
           limit: int = 8, modes: List[str] = None) -> List[dict]:
    body = {
        "query": query[:500],
        "limit": limit,
        "search_modes": modes or ["vector", "lexical", "graph", "temporal"],
    }
    if agent_id:
        body["agent_id"] = agent_id
    d = _post("/v1/memory/recall", body)
    return (d or {}).get("results", [])


def reflect(query: str, agent_id: Optional[str] = None,
            depth: str = "mid") -> str:
    body = {"query": query, "depth": depth}
    if agent_id:
        body["agent_id"] = agent_id
    d = _post("/v1/memory/reflect", body, timeout=20)
    return (d or {}).get("reflection", "")


def agent_context(agent_id: str, tokens: int = 2000) -> Optional[dict]:
    return _get(f"/v1/agents/{agent_id}/context?tokens={tokens}")


def save_lesson(content: str, agent_id: str) -> Optional[dict]:
    return _post("/v1/memory/save", {
        "content": content,
        "agent_id": agent_id,
        "memory_type": "lesson",
        "importance": 0.9,
    })


def update_agent_activity(agent_id: str, model: Optional[str] = None, 
                          capabilities: Optional[List[str]] = None) -> bool:
    """Update agent activity and metadata for registry enhancement."""
    body = {}
    if model:
        body["model"] = model
    if capabilities:
        body["capabilities"] = capabilities
    
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}/v1/agents/{agent_id}/update",
            data=json.dumps(body).encode(),
            headers=_headers(),
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False