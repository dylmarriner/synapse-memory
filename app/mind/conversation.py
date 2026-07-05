"""Conversation manager: multi-turn dialogues with the mind.

The mind supports multi-turn conversations where context carries
across turns.  The state is persisted to the database so a
conversation can survive a restart.  This is a pure in-memory
implementation; the persistence layer is layered on top by the
router when the DB is available.

Each turn:
  1. Builds context from the conversation history
  2. Calls mind.think() with that context
  3. Updates the conversation state
  4. Returns the MindResponse

At conversation end:
  1. Extracts insights from the full dialogue
  2. Updates the mind's identity with those insights
  3. Saves a session summary
  4. Clears the state
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.conversation")


@dataclass
class Turn:
    """One turn of a multi-turn conversation."""
    turn_number: int
    agent_message: str
    mind_response: Any                          # MindResponse — kept loose to avoid cycles
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConversationState:
    """The state of a single ongoing conversation."""
    conversation_id: str
    mind_id: str
    agent_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    turns: List[Turn] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def is_open(self) -> bool:
        return len(self.turns) == 0 or self.turns[-1].mind_response is not None


class ConversationManager:
    """Tracks multi-turn conversations with the mind.

    In production this is backed by the database via the
    `app.mind.persist` module.  When the manager is constructed
    with a `db` callable that returns an async session, every turn
    is persisted.

    The in-memory map is still the source of truth for an
    *active* conversation; the database is the audit log and the
    rehydration source after a restart.
    """

    def __init__(
        self,
        mind_id: str,
        mind: Any = None,
        db_session_factory: Any = None,
    ) -> None:
        self.mind_id = mind_id
        self.mind = mind
        self.db_factory = db_session_factory
        self.active: Dict[str, ConversationState] = {}

    def start_conversation(self, agent_id: str) -> str:
        conv_id = str(uuid.uuid4())
        self.active[conv_id] = ConversationState(
            conversation_id=conv_id,
            mind_id=self.mind_id,
            agent_id=agent_id,
        )
        log.debug("mind '%s' started conversation %s with %s", self.mind_id, conv_id, agent_id)
        return conv_id

    async def process_turn(
        self,
        conversation_id: str,
        message: str,
    ) -> Any:
        """Process one turn of conversation.

        Returns the MindResponse for this turn.  Raises KeyError if
        the conversation_id is unknown.
        """
        state = self.active.get(conversation_id)
        if state is None:
            raise KeyError(f"unknown conversation_id: {conversation_id}")
        if self.mind is None:
            raise RuntimeError("ConversationManager has no mind wired")

        # Build context from prior turns
        context = dict(state.context)
        context["agent_id"] = state.agent_id
        context["conversation_id"] = conversation_id
        if state.turns:
            # Include the last 3 turns as prior context
            context["prior_turns"] = [
                {"role": "agent", "content": t.agent_message}
                for t in state.turns[-3:]
            ] + [
                {"role": "mind", "content": (t.mind_response.answer if t.mind_response and t.mind_response.answer else "")}
                for t in state.turns[-3:]
            ]

        # Ask the mind
        response = await self.mind.think(question=message, context=context)

        # Update state
        turn = Turn(
            turn_number=len(state.turns) + 1,
            agent_message=message,
            mind_response=response,
        )
        state.turns.append(turn)

        # Persist the turn (fire-and-forget; never fail the agent)
        if self.db_factory is not None:
            try:
                async with self.db_factory() as db:
                    from app.mind import persist as _persist
                    await _persist.save_conversation_turn(
                        mind_id=self.mind_id,
                        conversation_id=conversation_id,
                        agent_id=state.agent_id,
                        turn_number=turn.turn_number,
                        agent_message=message,
                        mind_response=response,
                        db=db,
                    )
            except Exception as e:
                log.debug("persistence of turn failed: %s", e)

        return response

    async def end_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """End the conversation.  Returns a summary of what was learned."""
        state = self.active.pop(conversation_id, None)
        if state is None:
            return {"status": "unknown", "learnings_extracted": 0}
        insights = self._extract_insights(state)
        # Persist learnings to the mind's identity (when wired)
        if self.mind is not None and hasattr(self.mind, "learning"):
            try:
                await self.mind.learning.learn_from_session(
                    agent_id=state.agent_id,
                    session_summary=self._summarize(state),
                    insights=insights,
                )
            except Exception as e:
                log.debug("learning_from_session failed: %s", e)
        # Mark the conversation ended in the database
        if self.db_factory is not None:
            try:
                async with self.db_factory() as db:
                    from app.mind import persist as _persist
                    await _persist.end_conversation_in_db(conversation_id, db)
            except Exception as e:
                log.debug("end_conversation_in_db failed: %s", e)
        return {
            "status": "ended",
            "turn_count": len(state.turns),
            "learnings_extracted": len(insights),
            "insights": insights,
        }

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        return self.active.get(conversation_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_insights(self, state: ConversationState) -> List[str]:
        """Heuristic insight extraction: look for high-confidence turns
        and pull the conclusion out of each.  In production the LLM
        does this with a tailored prompt."""
        insights: List[str] = []
        for turn in state.turns:
            response = turn.mind_response
            if response is None:
                continue
            if getattr(response, "confidence", 0) >= 0.7 and getattr(response, "answer", None):
                insights.append(response.answer[:200])
        return insights[:5]

    def _summarize(self, state: ConversationState) -> str:
        if not state.turns:
            return f"Empty conversation with {state.agent_id}"
        turns = len(state.turns)
        first_msg = state.turns[0].agent_message[:100]
        return f"Conversation with {state.agent_id} ({turns} turns). Started with: {first_msg}"


__all__ = ["ConversationManager", "ConversationState", "Turn"]
