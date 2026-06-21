"""Nexus SDK — Python client for the Nexus unified AI memory server."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Callable, Optional

__version__ = "1.0.0"


class NexusError(Exception):
    """Raised when a Nexus API call fails."""


class NexusClient:
    """Python client for the Nexus memory server.

    Usage:
        client = NexusClient(secret="your-nexus-secret")
        client.save("Auth uses JWT RS256 rotation", importance=0.9, tags=["auth"])
        results = client.recall("authentication")
        ctx = client.context(agent_id="my-agent")
    """

    def __init__(
        self,
        url: str | None = None,
        secret: str | None = None,
        agent_id: str = "default",
    ):
        self.url   = (url    or os.environ.get("NEXUS_URL",    "http://100.93.75.87:7777")).rstrip("/")
        self.secret = secret or os.environ.get("NEXUS_SECRET", "")
        self.agent_id = agent_id
        self._on_save: list[Callable] = []
        self._on_recall: list[Callable] = []

    def on(self, event: str, callback: Callable) -> "NexusClient":
        """Register a lifecycle hook. Events: 'memory.save', 'memory.recall'"""
        if event == "memory.save":
            self._on_save.append(callback)
        elif event == "memory.recall":
            self._on_recall.append(callback)
        return self

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.secret:
            h["Authorization"] = f"Bearer {self.secret}"
        return h

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.url}{path}", data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise NexusError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            raise NexusError(f"Connection failed: {e.reason}")

    # ── Core API ──────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Check server health."""
        req = urllib.request.Request(f"{self.url}/health", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise NexusError(f"Health check failed: {e.reason}")

    def save(
        self,
        content: str,
        agent_id: str | None = None,
        memory_type: Optional[str] = None,
        importance: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a memory."""
        result = self._post("/v1/memory/save", {
            "content": content,
            "agent_id": agent_id or self.agent_id,
            "memory_type": memory_type,
            "importance": importance,
            "tags": tags or [],
            "metadata": metadata or {},
        })
        for cb in self._on_save:
            cb(result)
        return result

    def recall(
        self,
        query: str,
        agent_id: str | None = None,
        limit: int = 10,
        memory_types: list[str] | None = None,
        search_modes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search memories with 4-way hybrid recall."""
        result = self._post("/v1/memory/recall", {
            "query": query,
            "agent_id": agent_id or self.agent_id,
            "limit": limit,
            "memory_types": memory_types or [],
            "search_modes": search_modes or ["vector", "lexical", "graph", "temporal"],
        })
        for cb in self._on_recall:
            cb(result)
        return result

    def reflect(
        self,
        query: str,
        agent_id: str | None = None,
        depth: str = "mid",
        context: str | None = None,
    ) -> str:
        """LLM synthesis over recalled memories. Returns structured insight text."""
        result = self._post("/v1/memory/reflect", {
            "query": query,
            "agent_id": agent_id or self.agent_id,
            "depth": depth,
            "context": context,
        })
        return result.get("reflection", "")

    def context(
        self,
        agent_id: str | None = None,
        tokens: int = 2000,
    ) -> dict[str, Any]:
        """Get full agent context: representation, memories, conclusions, entities."""
        aid = agent_id or self.agent_id
        req = urllib.request.Request(
            f"{self.url}/v1/agents/{aid}/context?tokens={tokens}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise NexusError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")

    def learn(
        self,
        content: str,
        agent_id: str | None = None,
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Teach an agent something — saves immediately with async LLM extraction."""
        aid = agent_id or self.agent_id
        return self._post(f"/v1/agents/{aid}/learn", {
            "content": content,
            "importance": importance,
            "tags": tags or [],
        })

    def save_lesson(
        self,
        content: str,
        agent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Save a high-importance lesson (importance=0.9, never decayed)."""
        return self.save(
            content,
            agent_id=agent_id,
            memory_type="lesson",
            importance=0.9,
            tags=tags or [],
        )

    def save_global(
        self,
        content: str,
        memory_type: str = "world",
        importance: float = 0.6,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Save to the global shared pool — visible to every agent."""
        return self.save(content, agent_id="global", memory_type=memory_type,
                         importance=importance, tags=tags or [])

    def __enter__(self): return self
    def __exit__(self, *_): pass
