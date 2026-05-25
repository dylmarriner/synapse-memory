"""Synapse SDK — Python client for the Synapse Enterprise Memory system."""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

__version__ = "0.1.0"


class SynapseError(Exception):
    """Raised when a Synapse API call fails."""


@dataclass
class SynapseConfig:
    """Configuration for Synapse client."""

    server_url: str = os.environ.get("SYNAPSE_URL", "http://100.91.55.113:8765/mcp")
    api_key: str = os.environ.get("SYNAPSE_API_KEY", "")
    tenant_id: str = os.environ.get("SYNAPSE_TENANT_ID", "")
    default_project: str = os.environ.get("SYNAPSE_PROJECT", "default")
    timeout: int = 30
    auto_embed: bool = True
    auto_compress: bool = True


class SessionManager:
    """Manages MCP session lifecycle."""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self._session_id: str | None = None
        self._expires_at: float = 0

    def ensure_session(self) -> str:
        now = time.time()
        if self._session_id and now < self._expires_at:
            return self._session_id

        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "synapse-sdk-py", "version": __version__},
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            self.server_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            session_id = resp.headers.get("mcp-session-id") or ""
            if not session_id:
                raise SynapseError("Server did not return MCP session ID")
            self._session_id = session_id
            self._expires_at = now + 840  # 14 minutes (refresh before 15min expiry)
            return session_id


class SynapseClient:
    """Python client for Synapse Enterprise Memory.

    Usage:
        client = SynapseClient(api_key="syn_...")
        client.store(kind="semantic", content="Important note")
        results = client.retrieve("search query")
    """

    def __init__(
        self,
        server_url: str | None = None,
        api_key: str | None = None,
        tenant_id: str | None = None,
        default_project: str | None = None,
        config: SynapseConfig | None = None,
    ):
        self.config = config or SynapseConfig()
        if server_url:
            self.config.server_url = server_url
        if api_key:
            self.config.api_key = api_key
        if tenant_id:
            self.config.tenant_id = tenant_id
        if default_project:
            self.config.default_project = default_project

        self._session = SessionManager(self.config.server_url)

        # Lifecycle hooks
        self._on_store: list[Callable] = []
        self._on_retrieve: list[Callable] = []

    # ── Lifecycle Hooks ─────────────────────────────────────────────

    def on(self, event: str, callback: Callable):
        """Register a lifecycle hook.

        Events: 'memory.store', 'memory.retrieve'
        """
        if event == "memory.store":
            self._on_store.append(callback)
        elif event == "memory.retrieve":
            self._on_retrieve.append(callback)
        return self

    # ── Core MCP Call ───────────────────────────────────────────────

    def _call(self, tool: str, **params) -> dict[str, Any]:
        session_id = self._session.ensure_session()
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": params},
        }).encode("utf-8")

        req = urllib.request.Request(
            self.config.server_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Mcp-Session-Id": session_id,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise SynapseError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            raise SynapseError(f"Connection failed: {e.reason}")

        if "error" in data:
            raise SynapseError(data["error"].get("message", str(data["error"])))

        result = data.get("result", {})
        content = result.get("content", [])
        if content:
            try:
                return json.loads(content[0]["text"])
            except (json.JSONDecodeError, KeyError, IndexError):
                return {"ok": False, "error": "Failed to parse response"}

        return result.get("structuredContent", {})

    # ── Memory Operations ───────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Get server health status."""
        return self._call("health")

    def register_tenant(
        self, name: str = "", tier: str = "free", master_key: str = ""
    ) -> dict[str, Any]:
        """Register a new tenant. Returns API key."""
        return self._call(
            "register_tenant",
            name=name,
            tier=tier,
            master_key=master_key,
        )

    def store(
        self,
        content: str,
        project_key: str | None = None,
        kind: str = "episodic",
        tags: list[str] | None = None,
        importance: float = 0.5,
        source: str = "synapse-sdk-py",
        source_device: str = "",
        ttl: int = 0,
    ) -> dict[str, Any]:
        """Store a memory."""
        if not self.config.api_key and not self.config.tenant_id:
            raise SynapseError("api_key or tenant_id required")

        result = self._call(
            "store",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            project_key=project_key or self.config.default_project,
            kind=kind,
            content=content,
            tags=tags or [],
            importance=importance,
            source=source,
            source_device=source_device,
            ttl=ttl,
        )

        for cb in self._on_store:
            cb(result)

        return result

    def retrieve(
        self,
        query: str,
        project_key: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
        temporal_decay: bool = True,
    ) -> dict[str, Any]:
        """Search memories with hybrid retrieval."""
        result = self._call(
            "retrieve",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            query=query,
            project_key=project_key or self.config.default_project,
            kinds=kinds,
            limit=limit,
            min_score=min_score,
            temporal_decay=temporal_decay,
        )

        for cb in self._on_retrieve:
            cb(result)

        return result

    def update(
        self,
        memory_id: str,
        content: str,
        merge_strategy: str = "merge",
        tags: list[str] | None = None,
        importance: float | None = None,
    ) -> dict[str, Any]:
        """Update a memory."""
        return self._call(
            "update",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            memory_id=memory_id,
            content=content,
            merge_strategy=merge_strategy,
            tags=tags,
            importance=importance,
            source_device="synapse-sdk-py",
        )

    def delete(self, memory_id: str, reason: str = "") -> dict[str, Any]:
        """Delete a memory."""
        return self._call(
            "delete",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            memory_id=memory_id,
            reason=reason,
            source_device="synapse-sdk-py",
        )

    def context(
        self,
        query: str = "",
        project_key: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Get optimized context pack for prompt injection."""
        return self._call(
            "context",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            query=query,
            project_key=project_key or self.config.default_project,
            kinds=kinds,
            limit=limit,
        )

    def rank(
        self,
        project_key: str | None = None,
        limit: int = 20,
        min_importance: float = 0.0,
    ) -> dict[str, Any]:
        """Rank memories by importance."""
        return self._call(
            "rank",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            project_key=project_key or self.config.default_project,
            limit=limit,
            min_importance=min_importance,
        )

    def embed(self, texts: list[str]) -> dict[str, Any]:
        """Generate embeddings."""
        return self._call(
            "embed",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            texts=texts,
        )

    def compress(
        self,
        memory_ids: list[str],
        strategy: str = "deduplicate",
        max_tokens: int = 0,
    ) -> dict[str, Any]:
        """Compress memories."""
        return self._call(
            "compress",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            memory_ids=memory_ids,
            strategy=strategy,
            max_tokens=max_tokens,
        )

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Get a single memory by ID."""
        return self._call(
            "get_memory",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            memory_id=memory_id,
        )

    def list_memories(
        self,
        project_key: str | None = None,
        kind: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List memories with pagination."""
        return self._call(
            "list_memories",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
            project_key=project_key or "",
            kind=kind,
            limit=limit,
            offset=offset,
        )

    def get_tenant_info(self) -> dict[str, Any]:
        """Get tenant usage stats."""
        return self._call(
            "get_tenant_info",
            api_key=self.config.api_key,
            tenant_id=self.config.tenant_id,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
