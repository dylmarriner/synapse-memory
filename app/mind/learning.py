"""Learning system: the mind extracts patterns from every interaction.

Learning is what makes the mind *living* rather than just *responsive*.
After every interaction (and periodically between sessions), the
mind:

- Extracts a pattern from the question/answer pair
- Updates its identity (adds to capabilities/limitations)
- Forms or updates opinions based on the new evidence
- Prunes patterns that have aged out

The deterministic core does all of this without the LLM; the LLM
is used in production to extract the *content* of the pattern
from the interaction.  The LLM is optional — tests run without it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.learning")


# High-signal interaction patterns to extract deterministically.
_INTENT_PATTERNS = {
    "what": "factual_recall",
    "how": "procedural",
    "why": "causal_reasoning",
    "should": "decision_support",
    "tell me about": "exploratory",
    "remember": "memory_checkpoint",
    "forget": "memory_pruning",
    "reflect": "synthesis",
}


class LearningSystem:
    """Extracts patterns and updates identity after every interaction."""

    def __init__(
        self,
        mind_id: str,
        identity: Any,
        opinions: Any,
        memory_store: Any = None,
    ) -> None:
        self.mind_id = mind_id
        self.identity = identity
        self.opinions = opinions
        self.memory = memory_store

    async def learn_from_interaction(
        self,
        agent_id: str,
        question: str,
        response: Any,
    ) -> None:
        """Run after every think() call.  Cheap, side-effect only."""
        # 1. Update the relationship with this agent
        self.identity.record_interaction(agent_id, success=(response.confidence > 0.3))

        # 2. Extract a pattern from the intent (deterministic)
        intent_kind = self._classify_intent(question)
        if intent_kind:
            self.identity.add_pattern(
                description=f"Agent asks {intent_kind} questions",
                importance=0.4,
                source="interaction",
            )

        # 3. Record a learning if the response is high-quality
        if response.confidence >= 0.8:
            self.identity.add_capability(
                f"Confidently answered a {intent_kind or 'general'} question"
            )

        if response.confidence < 0.3 and response.answer is not None:
            self.identity.add_limitation(
                f"Struggled with a {intent_kind or 'general'} question"
            )

        # 4. Save a learning event to the log (when the DB is wired)
        if self.memory is not None:
            try:
                await self.memory.save_learning_event(
                    mind_id=self.mind_id,
                    kind="interaction_learning",
                    description=f"Interaction with {agent_id}: {intent_kind or 'general'}",
                    metadata={"confidence": response.confidence},
                )
            except Exception:
                # Don't fail the interaction if logging fails
                pass

    async def learn_from_session(
        self,
        agent_id: str,
        session_summary: str,
        insights: List[str],
    ) -> None:
        """Called at session end.  Updates identity with session learnings."""
        for insight in insights:
            self.identity.add_pattern(
                description=insight,
                importance=0.6,
                source="session",
            )
        self.identity.add_pattern(
            description=f"Worked with {agent_id} on a session",
            importance=0.3,
            source="session",
        )
        # Save the summary as a memory for future recall
        if self.memory is not None:
            try:
                await self.memory.save(
                    content=session_summary,
                    agent_id=agent_id,
                    memory_type="experience",
                    importance=0.7,
                    tags=["session_summary", agent_id],
                    mind_id=self.mind_id,
                )
            except Exception:
                pass

    async def periodic_learning(self, lookback_days: int = 7) -> None:
        """Run periodically (e.g. daily).  Prunes old patterns and
        consolidates the identity."""
        pruned = self.identity.prune_old_patterns(max_age_days=90, max_patterns=200)
        if pruned:
            log.info("mind '%s' pruned %d old patterns", self.mind_id, pruned)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_intent(self, question: str) -> Optional[str]:
        q = question.lower().strip()
        for prefix, kind in _INTENT_PATTERNS.items():
            if q.startswith(prefix):
                return kind
        return "general"


__all__ = ["LearningSystem"]
