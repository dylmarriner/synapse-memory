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

        1. Save the raw memory to the store
        2. Have the Mind process it (form opinions, update identity)
        3. Return the saved memory with Mind insights
        """
        memory = await self.mind.memory.save(
            content=content,
            agent_id=agent_id,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            mind_id=self.mind.mind_id,
        )
        # Let the Mind form opinions / update identity on this new
        # evidence.  We do a *cheap* think() in fast mode so the
        # save path stays snappy.
        try:
            await self.mind.think(
                question=content,
                context={"agent_id": agent_id, "auto_save": True},
                reasoning_depth="fast",
            )
        except Exception as e:
            log.debug("mind.think during save failed (non-fatal): %s", e)
        return {
            "id": memory.get("id"),
            "memory_type": memory_type,
            "importance": importance,
            "mind_processed": True,
        }

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
