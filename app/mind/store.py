"""Memory store adapter for the Living Mind.

The Mind reasons over *memories* but does not own the storage of
those memories.  This module is the seam: it adapts any object
that exposes a `recall()` coroutine to the interface the Mind
expects, and it provides the helper methods the Mind needs to
*write back* (save, save_learning_event, log_proactive).

The default adapter — `NexusMemoryStore` — wires the Mind to the
existing Nexus memory layer.  In tests we substitute the trivial
`InMemoryMindStore` which keeps everything in process and lets
the Mind run with no database.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.store")


class InMemoryMindStore:
    """Trivial in-memory store for tests and embedded use.

    Implements the minimal surface the Mind needs:
      - recall(query, agent_id, limit, mind_id) -> List[memory]
      - save(content, agent_id, memory_type, importance, tags, mind_id) -> dict
      - save_learning_event(mind_id, kind, description, metadata) -> None
      - log_proactive(mind_id, agent_id, item_type, content, relevance) -> None
    """

    def __init__(self) -> None:
        self.memories: List[Dict[str, Any]] = []
        self.learning_events: List[Dict[str, Any]] = []
        self.proactive_log: List[Dict[str, Any]] = []

    async def recall(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 20,
        mind_id: Optional[str] = None,
        container_tag: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Keyword-overlap recall.  Real backends would do vector + lexical + graph.

        Filters: agent_id, mind_id, container_tag, scope.  Scope is a
        prefix match (e.g. "auth.jwt" matches a memory with scope
        "auth.jwt.refresh").
        """
        from app.adopted import scope as _scope_mod
        q_tokens = {t.lower() for t in query.split() if len(t) > 2}
        scope_norm = _scope_mod.normalize(scope) if scope else None
        scored: List[tuple] = []
        for m in self.memories:
            if mind_id and m.get("mind_id") and m["mind_id"] != mind_id:
                continue
            if agent_id and m.get("agent_id") and m["agent_id"] != agent_id:
                continue
            if container_tag and m.get("container_tag") != container_tag:
                continue
            if scope_norm and not _scope_mod.matches(scope_norm, m.get("scope") or ""):
                continue
            content = (m.get("content") or "").lower()
            m_tokens = {t for t in content.split() if len(t) > 2}
            if q_tokens:
                score = len(q_tokens & m_tokens) / max(1, len(q_tokens))
            else:
                score = 0.0
            score += 0.1 * float(m.get("importance", 0.5) or 0.5)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for score, m in scored if score > 0][:limit]

    async def save(
        self,
        content: str,
        agent_id: Optional[str] = None,
        memory_type: str = "observation",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        mind_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        import uuid
        from datetime import datetime, timezone
        memory = {
            "id": str(uuid.uuid4()),
            "content": content,
            "agent_id": agent_id,
            "memory_type": memory_type,
            "importance": importance,
            "metadata": {"tags": tags or []},
            "mind_id": mind_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.memories.append(memory)
        return memory

    async def save_learning_event(
        self,
        mind_id: str,
        kind: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.learning_events.append({
            "mind_id": mind_id,
            "kind": kind,
            "description": description,
            "metadata": metadata or {},
        })

    async def log_proactive(
        self,
        mind_id: str,
        agent_id: Optional[str],
        item_type: str,
        content: str,
        relevance: float,
    ) -> None:
        self.proactive_log.append({
            "mind_id": mind_id,
            "agent_id": agent_id,
            "item_type": item_type,
            "content": content,
            "relevance": relevance,
        })


class NexusMemoryStore:
    """Adapter that wires the Mind to the existing Nexus memory layer.

    Uses the existing search functions (vector + lexical + graph + temporal)
    for recall, and the existing `save_memory` for writes.  Learning
    events and proactive logs are persisted to the new tables from
    migration 006.
    """

    def __init__(self, db_session_factory: Any = None) -> None:
        self.db = db_session_factory

    async def recall(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 20,
        mind_id: Optional[str] = None,
        container_tag: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recall through the existing Nexus 4-mode fused search."""
        try:
            # Import lazily to avoid hard-coupling the Mind package
            # to the Nexus router layer.
            from app.search.vector import vector_search
            from app.search.lexical import lexical_search
            from app.routers.memory import reciprocal_rank_fusion
            from sqlalchemy.ext.asyncio import AsyncSession
            # In a real call, we'd be inside an active request and
            # already have a session.  In standalone use, callers
            # pass a session via the `db` argument.  We support both.
            from app.db import SessionLocal
            async with SessionLocal() as session:
                vec = await vector_search(session, query, agent_id, None, limit)
                lex = await lexical_search(session, query, agent_id, None, limit)
                fused = reciprocal_rank_fusion([vec, lex])[:limit]
            results = []
            for m in fused:
                entry = {
                    "id": str(getattr(m, "id", "")),
                    "content": getattr(m, "content", ""),
                    "memory_type": getattr(m, "memory_type", "observation"),
                    "importance": float(getattr(m, "importance", 0.5) or 0.5),
                    "agent_id": str(getattr(m, "agent_id", "") or ""),
                    "metadata": dict(getattr(m, "metadata_", None) or {}),
                    "created_at": getattr(m, "created_at", None).isoformat() if getattr(m, "created_at", None) else None,
                    "mind_id": str(getattr(m, "mind_id", "") or "") or mind_id,
                    # Carry the adopted-pattern scoping columns through so the
                    # container_tag / scope filters below actually match.
                    "container_tag": getattr(m, "container_tag", None),
                    "scope": getattr(m, "scope", None),
                }
                # Apply container_tag / scope filters in-process as fallback
                if container_tag and entry.get("container_tag") != container_tag:
                    continue
                if scope:
                    from app.adopted import scope as _scope_mod
                    scope_norm = _scope_mod.normalize(scope)
                    mem_scope = entry.get("scope") or ""
                    if not _scope_mod.matches(scope_norm, mem_scope):
                        continue
                results.append(entry)
            return results
        except Exception as e:
            log.warning("NexusMemoryStore.recall failed: %s", e)
            return []

    async def save(
        self,
        content: str,
        agent_id: Optional[str] = None,
        memory_type: str = "observation",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        mind_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save through the existing Nexus save path."""
        try:
            from app.memory.ingest import save_memory
            from app.models.api import MemorySaveRequest
            from app.db import SessionLocal
            async with SessionLocal() as session:
                req = MemorySaveRequest(
                    content=content,
                    agent_id=agent_id or "global",
                    memory_type=memory_type,
                    importance=importance,
                    tags=tags or [],
                )
                # The Mind does not have direct access to the redis
                # client; the worker can pick up queued jobs async.
                # For now we just commit synchronously.
                from app.config import settings
                response = await save_memory(session, None, req)
            return {"id": str(response.id)}
        except Exception as e:
            log.warning("NexusMemoryStore.save failed: %s", e)
            return {"id": None, "error": str(e)}

    async def save_learning_event(
        self,
        mind_id: str,
        kind: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a learning event to mind_learning_events."""
        try:
            from sqlalchemy import text
            from app.db import SessionLocal
            async with SessionLocal() as session:
                # mind_id arrives as the stable mind *name* ("default"), not a
                # UUID — resolve it via the minds registry.  INSERT…SELECT means
                # a not-yet-persisted mind simply inserts nothing (no error)
                # instead of violating the NOT NULL on mind_id.
                await session.execute(text("""
                    INSERT INTO mind_learning_events (mind_id, kind, description, metadata, source)
                    SELECT m.id, :kind, :desc, CAST(:meta AS jsonb), :src
                    FROM minds m WHERE m.name = :name
                """), {
                    "name": mind_id,
                    "kind": kind,
                    "desc": description,
                    "meta": __import__("json").dumps(metadata or {}),
                    "src": (metadata or {}).get("source", "interaction"),
                })
                await session.commit()
        except Exception as e:
            log.debug("save_learning_event failed: %s", e)

    async def log_proactive(
        self,
        mind_id: str,
        agent_id: Optional[str],
        item_type: str,
        content: str,
        relevance: float,
    ) -> None:
        """Log a proactive surfacing event."""
        try:
            from sqlalchemy import text
            from app.db import SessionLocal
            async with SessionLocal() as session:
                # mind_id is a name; agent_id may be a name or None.  Resolve
                # both through the registries via INSERT…SELECT so a missing
                # mind row inserts nothing rather than raising.
                await session.execute(text("""
                    INSERT INTO mind_proactive_log
                        (mind_id, agent_id, item_type, content, relevance)
                    SELECT m.id,
                           (SELECT id FROM agents WHERE name = :aid LIMIT 1),
                           :kind, :content, :rel
                    FROM minds m WHERE m.name = :name
                """), {
                    "name": mind_id,
                    "aid": agent_id,
                    "kind": item_type,
                    "content": content,
                    "rel": relevance,
                })
                await session.commit()
        except Exception as e:
            log.debug("log_proactive failed: %s", e)


__all__ = ["InMemoryMindStore", "NexusMemoryStore"]
