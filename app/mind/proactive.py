"""Proactive surfacing: the mind pushes relevant context without being asked.

Proactive items are categorised by *why* they matter:

    unfinished_promise — the agent committed to something and hasn't done it
    recent_work        — related work in the last 7 days
    contradiction      — something the agent is doing now disagrees with a memory
    pattern            — a learned pattern that applies here
    temporal           — time-sensitive (deadline, due date, etc.)
    relationship       — insight about the relationship with the current agent

The deterministic core does all of this without the LLM; in
production the LLM call is used to *rank* candidates and to extract
the patterns and contradictions from the raw memory text.  The
heuristics here give a useful baseline that the LLM refines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.proactive")


@dataclass
class ProactiveItem:
    """One item the mind is proactively offering to the agent."""
    type: str                                  # unfinished_promise | recent_work | contradiction | pattern | temporal | relationship
    content: str
    relevance: float = 0.5                      # 0..1
    source_memory_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "relevance": self.relevance,
            "source_memory_id": self.source_memory_id,
            "created_at": self.created_at.isoformat(),
        }


# Markers that suggest a memory contains a commitment
_PROMISE_MARKERS = (
    "i will", "i'll", "i promise", "we should", "i should", "we need to",
    "let me", "going to", "todo:", "plan to", "need to",
)


class ProactiveSurfacing:
    """Proactive context manager for the living mind.

    The mind calls this on every think() to surface items the agent
    should know about.  Items are ranked by relevance and the top
    `max_items` are returned.
    """

    def __init__(self, mind_id: str, memory_store: Any = None, max_items: int = 5) -> None:
        self.mind_id = mind_id
        self.memory = memory_store
        self.max_items = max_items

    async def identify_context(
        self,
        question: str,
        memories: List[Dict[str, Any]],
        agent_id: Optional[str] = None,
    ) -> List[ProactiveItem]:
        """Identify proactive context items relevant to the question.

        Returns up to `max_items` items, ranked by relevance.
        """
        items: List[ProactiveItem] = []
        items.extend(self._unfinished_promises(memories, question))
        items.extend(self._recent_related_work(memories, question))
        items.extend(self._contradictions(memories, question))
        items.extend(self._time_sensitive(memories, question))
        items.extend(self._relationship_insights(agent_id))
        # Rank and take the top
        items.sort(key=lambda i: i.relevance, reverse=True)
        return items[: self.max_items]

    # ------------------------------------------------------------------
    # Individual surfacing rules
    # ------------------------------------------------------------------

    def _unfinished_promises(
        self, memories: List[Dict[str, Any]], question: str
    ) -> List[ProactiveItem]:
        """Find memories that look like commitments the agent hasn't
        fulfilled yet.  Heuristic: any memory containing a promise
        marker.  We match the substring directly rather than
        word-boundary because the markers ('i will', 'i should')
        don't naturally have word boundaries at the end.
        """
        items: List[ProactiveItem] = []
        question_tokens = {t.lower() for t in question.split() if len(t) > 2}
        for m in memories:
            content = (m.get("content") or m.get("text") or "").lower()
            if not any(mk in content for mk in _PROMISE_MARKERS):
                continue
            # If the question is about a related topic, boost relevance
            relevance = self._text_relevance(content, question_tokens)
            items.append(ProactiveItem(
                type="unfinished_promise",
                content=f"You committed to: {m.get('content') or m.get('text')}",
                relevance=0.6 + 0.4 * relevance,
                source_memory_id=m.get("id"),
            ))
        return items

    def _recent_related_work(
        self, memories: List[Dict[str, Any]], question: str
    ) -> List[ProactiveItem]:
        """Recent memories (last 7 days) that mention the same topic."""
        items: List[ProactiveItem] = []
        question_tokens = {t.lower() for t in question.split() if len(t) > 2}
        if not question_tokens:
            return items
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for m in memories:
            created = self._parse_dt(m.get("created_at"))
            if not created or created < cutoff:
                continue
            content = (m.get("content") or m.get("text") or "").lower()
            relevance = self._text_relevance(content, question_tokens)
            if relevance > 0.1:
                items.append(ProactiveItem(
                    type="recent_work",
                    content=f"Recent: {m.get('content') or m.get('text')}",
                    relevance=0.5 * relevance,
                    source_memory_id=m.get("id"),
                ))
        return items

    def _contradictions(
        self, memories: List[Dict[str, Any]], question: str
    ) -> List[ProactiveItem]:
        """Flag memories that look like they contradict the question.

        Deterministic version: look for negation words + topic
        overlap.  LLM override catches subtler cases.
        """
        items: List[ProactiveItem] = []
        neg = {"not", "never", "no longer", "doesn't", "won't", "can't", "shouldn't"}
        question_tokens = {t.lower() for t in question.split() if len(t) > 2}
        for m in memories:
            content = (m.get("content") or m.get("text") or "")
            low = content.lower()
            if not any(n in low for n in neg):
                continue
            relevance = self._text_relevance(low, question_tokens)
            if relevance > 0.2:
                items.append(ProactiveItem(
                    type="contradiction",
                    content=f"Note: {content[:200]}",
                    relevance=0.7 * relevance,
                    source_memory_id=m.get("id"),
                ))
        return items

    def _time_sensitive(
        self, memories: List[Dict[str, Any]], question: str
    ) -> List[ProactiveItem]:
        """Time-sensitive items: deadlines, due dates, expirations."""
        items: List[ProactiveItem] = []
        time_words = {"deadline", "due", "expires", "urgent", "asap", "tomorrow", "today"}
        question_tokens = {t.lower() for t in question.split() if len(t) > 2}
        for m in memories:
            content = (m.get("content") or m.get("text") or "").lower()
            if not any(w in content for w in time_words):
                continue
            relevance = self._text_relevance(content, question_tokens)
            items.append(ProactiveItem(
                type="temporal",
                content=f"Time-sensitive: {m.get('content') or m.get('text')}",
                relevance=0.6 + 0.3 * relevance,
                source_memory_id=m.get("id"),
            ))
        return items

    def _relationship_insights(self, agent_id: Optional[str]) -> List[ProactiveItem]:
        """Empty in the default impl.  The Identity system fills
        these in if it's available on the mind."""
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_relevance(text: str, query_tokens: set) -> float:
        """Token overlap: 0..1."""
        if not query_tokens:
            return 0.0
        text_tokens = {t for t in text.split() if len(t) > 2}
        if not text_tokens:
            return 0.0
        return len(text_tokens & query_tokens) / max(1, len(query_tokens))

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None


__all__ = ["ProactiveSurfacing", "ProactiveItem"]
