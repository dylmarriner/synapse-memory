"""Memory store adapter for the Living Mind.

The Mind reasons over memories but does not own the storage of those
memories. This module adapts the existing Nexus memory layer to the
interface the mind expects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.store")


class InMemoryMindStore:
    """Trivial in-memory store for tests and embedded use."""

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
            score = (len(q_tokens & m_tokens) / max(1, len(q_tokens))) if q_tokens else 0.0
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
    """Adapter that wires the Mind to the existing Nexus memory layer."""

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
        """Recall through the Nexus fused search, enriched with structure."""
        try:
            from app.search.vector import vector_search
            from app.search.lexical import lexical_search
            from app.search.graph import graph_search
            from app.search.temporal import temporal_search
            from app.search.expand import expand_query
            from app.search.fusion import reciprocal_rank_fusion
            from app.search.rerank import rerank as rerank_results
            from app.db import SessionLocal

            async with SessionLocal() as session:
                expanded_query = await expand_query(query)
                vec = await vector_search(session, expanded_query, agent_id, None, limit * 2)
                lex = await lexical_search(session, query, agent_id, None, limit * 2)
                graph = await graph_search(session, query, agent_id, max(4, limit))
                temporal = await temporal_search(session, query, agent_id, None, max(4, limit))
                fused = reciprocal_rank_fusion([vec, lex, graph, temporal])[: max(limit * 2, limit)]
                fused = await rerank_results(query, fused, limit)
                enrichment = await self._enrich_memories(
                    session,
                    [str(getattr(m, "id", "") or "") for m in fused if getattr(m, "id", None)],
                )

            results = []
            for m in fused:
                mem_id = str(getattr(m, "id", "") or "")
                extra = enrichment.get(mem_id, {})
                meta_raw = getattr(m, "metadata", None)
                if meta_raw is None:
                    meta_raw = getattr(m, "metadata_", None)
                meta = dict(meta_raw or {})
                meta.update({
                    "layer": extra.get("layer"),
                    "activation_score": extra.get("activation_score"),
                    "layer_verification": extra.get("verification"),
                    "related_memory_ids": extra.get("related_memory_ids", []),
                    "relation_kinds": extra.get("relation_kinds", []),
                    "relation_count": extra.get("relation_count", 0),
                })
                entry = {
                    "id": mem_id,
                    "content": getattr(m, "content", ""),
                    "memory_type": getattr(m, "memory_type", "observation"),
                    "importance": float(getattr(m, "importance", 0.5) or 0.5),
                    "agent_id": str(getattr(m, "agent_id", "") or "") or None,
                    "metadata": meta,
                    "created_at": getattr(m, "created_at", None).isoformat() if getattr(m, "created_at", None) else None,
                    "mind_id": mind_id,
                    "container_tag": getattr(m, "container_tag", None),
                    "scope": getattr(m, "scope", None),
                    "matched_by": list(getattr(m, "matched_by", []) or []),
                    "score": float(getattr(m, "score", 0.0) or 0.0),
                    "relevance": float(getattr(m, "relevance", 0.0) or 0.0),
                    "confidence": float(getattr(m, "confidence", 1.0) or 1.0),
                    "layer": extra.get("layer"),
                    "activation_score": extra.get("activation_score"),
                    "verification": extra.get("verification"),
                    "related_memory_ids": extra.get("related_memory_ids", []),
                    "relation_kinds": extra.get("relation_kinds", []),
                    "relation_count": extra.get("relation_count", 0),
                }
                if container_tag and entry.get("container_tag") != container_tag:
                    continue
                if scope:
                    from app.adopted import scope as _scope_mod
                    scope_norm = _scope_mod.normalize(scope)
                    mem_scope = entry.get("scope") or ""
                    if not _scope_mod.matches(scope_norm, mem_scope):
                        continue
                results.append(entry)

            # Honesty gate: mirror the plain /recall endpoint's relevance floor
            # so mind-routed recall can't surface 0.0-relevance noise just
            # because it skipped the regular recall path. "I don't have that"
            # beats a confident-sounding answer built on a garbage match.
            from app.config import settings as _gate
            min_rel = _gate.recall_min_relevance
            if min_rel > 0:
                results = [r for r in results if (r.get("relevance") or 0.0) >= min_rel]

            return results
        except Exception as e:
            log.warning("NexusMemoryStore.recall failed: %s", e)
            return []

    async def _enrich_memories(self, session: Any, memory_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not memory_ids:
            return {}
        from sqlalchemy import text
        rows = (await session.execute(text("""
            SELECT m.id::text AS id,
                   ml.layer AS layer,
                   ml.activation_score AS activation_score,
                   ml.verification AS verification,
                   COUNT(DISTINCT l.id) AS relation_count,
                   COALESCE(
                       array_agg(DISTINCT CASE WHEN other.id IS NOT NULL THEN other.id::text END)
                       FILTER (WHERE other.id IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS related_ids,
                   COALESCE(
                       array_agg(DISTINCT l.kind) FILTER (WHERE l.kind IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS relation_kinds
            FROM memories m
            LEFT JOIN memory_layers ml ON ml.memory_id = m.id
            LEFT JOIN memory_links l ON (l.src_id = m.id OR l.dst_id = m.id)
            LEFT JOIN memories other ON other.id = CASE WHEN l.src_id = m.id THEN l.dst_id ELSE l.src_id END
                                     AND other.superseded_by IS NULL
            WHERE m.id = ANY(CAST(:ids AS uuid[]))
            GROUP BY m.id, ml.layer, ml.activation_score, ml.verification
        """), {"ids": memory_ids})).fetchall()
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            rid = str(r.id)
            out[rid] = {
                "layer": r.layer,
                "activation_score": float(r.activation_score or 0.0),
                "verification": r.verification,
                "relation_count": int(r.relation_count or 0),
                "related_memory_ids": [x for x in (r.related_ids or []) if x and x != rid][:8],
                "relation_kinds": [x for x in (r.relation_kinds or []) if x],
            }
        return out

    async def get_related(
        self,
        memory_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return structurally-linked active memories around `memory_id`."""
        try:
            from sqlalchemy import text
            from app.db import SessionLocal
            async with SessionLocal() as session:
                rows = (await session.execute(text("""
                    SELECT other.id::text AS id,
                           other.content,
                           other.memory_type,
                           other.importance,
                           other.agent_id::text AS agent_id,
                           other.created_at,
                           other.metadata,
                           other.confidence,
                           ml.layer,
                           ml.activation_score,
                           ml.verification,
                           l.kind,
                           l.weight
                    FROM memory_links l
                    JOIN memories other
                      ON other.id = CASE WHEN l.src_id = CAST(:mid AS uuid) THEN l.dst_id ELSE l.src_id END
                    LEFT JOIN memory_layers ml ON ml.memory_id = other.id
                    WHERE (l.src_id = CAST(:mid AS uuid) OR l.dst_id = CAST(:mid AS uuid))
                      AND other.superseded_by IS NULL
                    ORDER BY
                      CASE l.kind
                        WHEN 'supersedes' THEN 4
                        WHEN 'related' THEN 3
                        WHEN 'derived_from' THEN 2
                        WHEN 'parent_of' THEN 1
                        WHEN 'child_of' THEN 1
                        ELSE 0
                      END DESC,
                      l.weight DESC,
                      other.importance DESC,
                      other.created_at DESC
                    LIMIT :limit
                """), {"mid": memory_id, "limit": limit})).fetchall()
            return [
                {
                    "id": r.id,
                    "content": r.content,
                    "memory_type": r.memory_type,
                    "importance": float(r.importance or 0.0),
                    "agent_id": r.agent_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "metadata": dict(r.metadata or {}),
                    "confidence": float(r.confidence or 1.0),
                    "layer": r.layer,
                    "activation_score": float(r.activation_score or 0.0),
                    "verification": r.verification,
                    "link_kind": r.kind,
                    "link_weight": float(r.weight or 0.0),
                    "matched_by": ["graph"],
                }
                for r in rows
            ]
        except Exception as e:
            log.debug("NexusMemoryStore.get_related failed: %s", e)
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
        try:
            from sqlalchemy import text
            from app.db import SessionLocal
            async with SessionLocal() as session:
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
        try:
            from sqlalchemy import text
            from app.db import SessionLocal
            async with SessionLocal() as session:
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
