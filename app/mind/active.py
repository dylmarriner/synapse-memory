"""Active Memory Layer: makes the Living Mind the default memory for agents.

This module wires the Mind into the existing Nexus memory operations
so that *every* `memory_save` / `memory_recall` call goes through
the Mind automatically.  The agent doesn't need to know the Mind
exists — it just calls memory tools, and the Mind reasons about
what's stored and retrieved.

Three pieces:

  MemoryRouter  — transparent wrapper around save/recall that
                  adds Mind processing on the way through.
  ContextInjector — builds the system-prompt briefing for an agent
                  from the Mind's identity + proactive context.
  ProactiveManager — runs at every turn to surface relevant items.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.mind import LivingMind, MindConfig, ReasoningDepth
from app.mind.store import InMemoryMindStore, NexusMemoryStore

log = logging.getLogger("nexus.mind.active")


class MemoryRouter:
    """Routes all memory operations through the living mind.

    Wraps an existing memory backend (InMemoryMindStore or
    NexusMemoryStore) and adds Mind processing on every operation:

      - save():   saved memory is also processed by the Mind, which
                  extracts entities, forms opinions, and updates
                  its identity.
      - recall(): recall is replaced by `mind.think()` — the agent
                  gets a *reasoned* answer, not just a list of
                  matches.

    The agent calls `memory_save` and `memory_recall` as usual; the
    router is mounted in front of the actual tools and the agent
    never sees the difference.
    """

    def __init__(self, mind: LivingMind) -> None:
        self.mind = mind

    async def save(
        self,
        content: str,
        agent_id: Optional[str] = None,
        memory_type: str = "observation",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Save through the mind.

        Two hard rules, enforced by code rather than left to the LLM's
        discretion:

        1. A save request is never dropped. Whatever happens to
           classification or reasoning below, the raw content always
           ends up persisted — worst case via `_force_raw_save`.
        2. The mind — not the caller — decides *where and how* the
           memory is stored: its real type and importance, based on
           the content itself, rather than trusting the agent's
           (often lazy/default) guess. The caller's values are only a
           fallback if classification fails.

        After that, the mind reasons over the new memory (forms
        opinions, updates identity) — that step is best-effort and
        never allowed to block or fail the save itself.
        """
        classified_type, classified_importance = await self._classify(content, memory_type, importance)

        memory: Dict[str, Any] = {}
        try:
            memory = await self.mind.memory.save(
                content=content,
                agent_id=agent_id,
                memory_type=classified_type,
                importance=classified_importance,
                tags=tags,
                mind_id=self.mind.mind_id,
            ) or {}
        except Exception as e:
            log.warning("mind.memory.save raised, falling back to forced raw save: %s", e)

        if not memory.get("id"):
            memory = await self._force_raw_save(content, agent_id, classified_type, classified_importance, tags)

        # Let the Mind form an opinion / update identity on this new
        # evidence.  This is *not* routed through think() — content is a
        # stored fact, not a question, and forcing it through the Q&A
        # intent classifier misclassifies statements as recall queries.
        # Form the opinion directly against the extracted topic instead.
        try:
            topic = self.mind._extract_topic(content)
            if topic:
                await self.mind.opinions.form_or_update(
                    topic=topic,
                    evidence=[memory],
                )
        except Exception as e:
            log.debug("mind opinion-forming during save failed (non-fatal): %s", e)

        return {
            "id": memory.get("id"),
            "memory_type": classified_type,
            "importance": classified_importance,
            "mind_processed": True,
        }

    async def _classify(self, content: str, fallback_type: str, fallback_importance: float) -> tuple[str, float]:
        """Ask the mind's LLM what this memory actually is.

        The caller's memory_type/importance are a fallback, not a default
        to trust — most callers pass "observation"/0.5 regardless of what
        the content actually is. If classification fails for any reason,
        fall back to the caller's values so the save still proceeds.
        """
        try:
            from app.llm import get_llm_client
            from app.memory.extract import _batch_extract
            llm = get_llm_client()
            if llm is None:
                return fallback_type, fallback_importance
            extracted = await _batch_extract(content, llm, importance=fallback_importance)
            classified_type = extracted.get("memory_type") or fallback_type
            return classified_type, fallback_importance
        except Exception as e:
            log.debug("mind classification failed, keeping caller-provided type: %s", e)
            return fallback_type, fallback_importance

    async def _force_raw_save(
        self,
        content: str,
        agent_id: Optional[str],
        memory_type: str,
        importance: float,
        tags: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Last-resort guarantee: a save request must never be silently lost.

        Bypasses classification, dedup, and everything else in the normal
        pipeline and writes the memory directly.
        """
        import json
        from sqlalchemy import text
        from app.db import SessionLocal
        from app.embeddings import get_embedding
        from app.memory.ingest import _ensure_agent

        try:
            async with SessionLocal() as session:
                agent = await _ensure_agent(session, agent_id or "global")
                emb = None
                try:
                    emb = await get_embedding(content)
                except Exception as e:
                    log.debug("embedding failed during forced raw save: %s", e)
                vec = "[" + ",".join(str(x) for x in emb) + "]" if emb else None
                row = (await session.execute(text("""
                    INSERT INTO memories (agent_id, content, memory_type, importance, metadata, embedding)
                    VALUES (:agent_id, :content, :memory_type, :importance, CAST(:meta AS jsonb), CAST(:embedding AS vector))
                    RETURNING id
                """), {
                    "agent_id": agent.id if agent else None,
                    "content": content,
                    "memory_type": memory_type,
                    "importance": importance,
                    "meta": json.dumps({"tags": tags or [], "forced_raw_save": True}),
                    "embedding": vec,
                })).first()
                await session.commit()
                return {"id": str(row[0])} if row else {"id": None}
        except Exception as e:
            log.error("forced raw save also failed — memory lost: %s", e)
            return {"id": None, "error": str(e)}

    async def recall(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 10,
        memory_types: Optional[List[str]] = None,
        reasoning_depth: str = "standard",
    ) -> Dict[str, Any]:
        """Recall through the mind.

        Returns a *reasoned* response: the mind's answer, the
        memories it cited, and any proactive context it surfaced.
        Not just a list of matches.
        """
        response = await self.mind.think(
            question=query,
            context={"agent_id": agent_id},
            reasoning_depth=reasoning_depth,
        )
        return {
            "answer": response.answer,
            "confidence": response.confidence,
            "memories_cited": response.memories_cited,
            "proactive_context": [item.to_dict() for item in response.proactive_context],
            "reasoning_trace": response.reasoning_trace.to_dict() if response.reasoning_trace else None,
        }


class ContextInjector:
    """Builds the system-prompt briefing for an agent.

    Called at session start (and optionally after every turn) to
    inject the Mind's context into the agent's system prompt:

      - Mind identity (core traits, learned patterns, capabilities)
      - Proactive context (unfinished promises, recent work, etc.)
      - Recent work summary
      - Unfinished promises
      - Relationship context

    Returns a string that the agent's hook layer prepends to the
    system prompt.  No I/O is done by this class itself — it
    delegates to the Mind and the ProactiveManager.
    """

    def __init__(self, mind: LivingMind) -> None:
        self.mind = mind

    async def build_briefing(
        self,
        agent_id: Optional[str] = None,
        current_question: Optional[str] = None,
        max_proactive: int = 5,
    ) -> str:
        """Build the briefing text the agent sees in its system prompt."""
        parts: List[str] = []

        # 1. Mind identity
        identity = self.mind.identity.to_dict()
        parts.append(self._format_identity(identity))

        # 2. Proactive context
        proactive = await self.mind.proactive.identify_context(
            current_question or "",
            memories=[],
            agent_id=agent_id,
        )
        if proactive:
            parts.append(self._format_proactive(proactive[:max_proactive]))

        # 3. Relationship context
        if agent_id and agent_id in self.mind.identity.relationships:
            rel = self.mind.identity.relationships[agent_id]
            parts.append(self._format_relationship(rel))

        return "\n\n".join(parts)

    @staticmethod
    def _format_identity(identity: Dict[str, Any]) -> str:
        core = identity.get("core_traits", [])[:3]
        traits = "\n".join(f"  - {t}" for t in core)
        return f"""## Living Mind Identity

You are working with a living mind that has:
{traits}
- {len(identity.get('learned_patterns', []))} learned patterns from experience
- {len(identity.get('capabilities', []))} known capabilities
- {len(identity.get('relationships', {}))} relationships

The mind reasons about memories, forms opinions, and proactively surfaces context. Trust its reasoning."""

    @staticmethod
    def _format_proactive(items: List[Any]) -> str:
        if not items:
            return ""
        lines = ["## Proactive Context\n\nThe mind has surfaced these relevant items:"]
        for item in items[:5]:
            rel = getattr(item, "relevance", 0.5)
            content = getattr(item, "content", "")
            lines.append(f"- {content} (relevance: {rel:.2f})")
        return "\n".join(lines)

    @staticmethod
    def _format_relationship(rel: Any) -> str:
        return f"""## Relationship Context

You've worked with this agent {rel.interaction_count} times.
Trust level: {rel.trust_level:.2f}
Shared projects: {', '.join(rel.shared_projects[:3])}
Communication style: {rel.communication_style or 'unknown'}"""


class ProactiveManager:
    """Surfaces proactive context to an agent.

    A thin wrapper over the Mind's `proactive.identify_context()` that
    also logs each surfacing event to the database (so we can
    measure relevance over time).
    """

    def __init__(self, mind: LivingMind) -> None:
        self.mind = mind

    async def surface(
        self,
        agent_id: Optional[str] = None,
        question: Optional[str] = None,
    ) -> List[Any]:
        items = await self.mind.proactive.identify_context(
            question=question or "",
            memories=[],
            agent_id=agent_id,
        )
        # Log each item so we can learn which are useful
        if hasattr(self.mind.memory, "log_proactive"):
            for item in items:
                try:
                    await self.mind.memory.log_proactive(
                        mind_id=self.mind.mind_id,
                        agent_id=agent_id,
                        item_type=getattr(item, "type", "unknown"),
                        content=getattr(item, "content", ""),
                        relevance=getattr(item, "relevance", 0.5),
                    )
                except Exception as e:
                    log.debug("log_proactive failed: %s", e)
        return items


__all__ = ["MemoryRouter", "ContextInjector", "ProactiveManager"]
