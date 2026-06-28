"""Opinion system: forms and maintains opinions from accumulated evidence.

An opinion is the mind's *stance* on a topic, with a confidence
score derived from how much evidence supports it.  Opinions are
distinct from memories in that they aggregate many memories into
a single point of view that the mind can express.

The deterministic core (stance counting, evidence threshold) is
in this module.  In production, an LLM call classifies each
piece of evidence as positive / negative / neutral toward the
topic; the LLM result is then passed to `form_or_update()` which
does the actual stance and strength math.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.opinions")


class Stance(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


# Evidence threshold: don't form a strong opinion on less than this
# many pieces of evidence.  The mind can still express a weak
# opinion below the threshold — it just won't update the stored one.
MIN_EVIDENCE_FOR_STRONG_OPINION = 3


@dataclass
class Opinion:
    """The mind's stance on a single topic."""
    topic: str
    stance: Stance = Stance.NEUTRAL
    strength: float = 0.5                       # 0..1
    rationale: Optional[str] = None
    evidence_count: int = 0
    memory_ids: List[str] = field(default_factory=list)
    formed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "stance": self.stance.value,
            "strength": self.strength,
            "rationale": self.rationale,
            "evidence_count": self.evidence_count,
            "memory_ids": list(self.memory_ids),
            "formed_at": self.formed_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }


class OpinionSystem:
    """The mind's opinion store.

    In production, `form_or_update()` is called with a hint from the
    reasoning layer about the stance the evidence supports.  The
    deterministic fallback classifies the evidence itself when
    no hint is provided.
    """

    def __init__(self, mind_id: str) -> None:
        self.mind_id = mind_id
        self.opinions: Dict[str, Opinion] = {}

    def get(self, topic: str) -> Optional[Opinion]:
        return self.opinions.get(topic.lower())

    def list(self) -> List[Opinion]:
        return list(self.opinions.values())

    async def form_or_update(
        self,
        topic: str,
        evidence: List[Dict[str, Any]],
        current_stance_hint: Optional[str] = None,
        llm_opinion: Optional[Any] = None,
    ) -> Optional[Opinion]:
        """Form a new opinion or update the existing one for this topic.

        `llm_opinion` is an `OpinionDraft` (stance, strength, reasoning,
        evidence).  When supplied it overrides both the hint and the
        deterministic classifier — the LLM is the more reliable source.

        Returns the updated opinion, or None if there is not enough
        evidence to form a meaningful stance.
        """
        topic = topic.lower().strip()
        if not evidence and current_stance_hint is None and llm_opinion is None:
            return None
        if not topic:
            return None

        # Prefer the LLM's opinion when available.
        llm_rationale: Optional[str] = None
        if llm_opinion is not None and not getattr(llm_opinion, "error", None):
            try:
                new_stance = Stance(getattr(llm_opinion, "stance", "neutral") or "neutral")
            except ValueError:
                new_stance = Stance.NEUTRAL
            new_strength = float(getattr(llm_opinion, "strength", 0.0) or 0.0)
            new_strength = max(0.0, min(1.0, new_strength))
            llm_rationale = (getattr(llm_opinion, "reasoning", "") or "").strip() or None
        else:
            # Fall back to hint, then deterministic classifier
            if current_stance_hint is None:
                current_stance_hint = self._classify_evidence(evidence, topic)
            new_stance, new_strength = self._aggregate(evidence, current_stance_hint)

        # Look up the existing opinion
        existing = self.opinions.get(topic)
        if existing is None:
            opinion = Opinion(
                topic=topic,
                stance=new_stance,
                strength=new_strength,
                rationale=llm_rationale,
                evidence_count=len(evidence),
                memory_ids=[m.get("id", "") for m in evidence if m.get("id")][:20],
            )
            self.opinions[topic] = opinion
            log.debug("mind '%s' formed opinion: %s = %s (%.2f)", self.mind_id, topic, new_stance.value, new_strength)
            return opinion

        # Update: weighted average of old and new strength
        total_count = existing.evidence_count + len(evidence)
        if total_count == 0:
            if llm_rationale:
                existing.rationale = llm_rationale
            return existing
        old_weight = existing.evidence_count / total_count
        new_weight = len(evidence) / total_count
        # If the new evidence clearly disagrees, let it dominate
        if existing.stance != Stance.NEUTRAL and new_stance != Stance.NEUTRAL and existing.stance != new_stance:
            # Contradiction: weaken the old stance rather than averaging
            combined_strength = max(0.0, existing.strength * old_weight - 0.1) + new_strength * new_weight
            new_stance = new_stance
        else:
            combined_strength = existing.strength * old_weight + new_strength * new_weight
        existing.stance = new_stance
        existing.strength = min(1.0, combined_strength)
        existing.evidence_count = total_count
        if llm_rationale:
            existing.rationale = llm_rationale
        existing.memory_ids = list({
            *(existing.memory_ids or []),
            *(m.get("id", "") for m in evidence if m.get("id")),
        })[:20]
        existing.last_updated = datetime.now(timezone.utc)
        return existing

    async def update(self, topic: str, new_evidence: Dict[str, Any]) -> Optional[Opinion]:
        """Convenience: update with a single new piece of evidence."""
        return await self.form_or_update(topic, [new_evidence])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify_evidence(self, evidence: List[Dict[str, Any]], topic: str) -> str:
        """Deterministic fallback: count positive vs negative markers
        in the evidence text.  Real callers should pass a hint from
        the LLM; this is the no-LLM path used in tests and as a
        safety net."""
        topic_low = topic.lower()
        positive = {"works", "good", "great", "fixed", "shipped", "success", "positive", "loves", "prefer"}
        negative = {"broken", "bug", "fails", "bad", "fails", "negative", "hates", "avoids", "frustrated"}
        pos = neg = 0
        for ev in evidence:
            text = ((ev.get("content") or ev.get("text") or "") + " " + topic_low).lower()
            pos += sum(1 for w in positive if w in text)
            neg += sum(1 for w in negative if w in text)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"

    def _aggregate(
        self,
        evidence: List[Dict[str, Any]],
        stance_hint: str,
    ) -> tuple:
        """Combine the evidence count with the hint to produce a
        (stance, strength) pair.  The strength is the evidence count
        capped at a confidence ceiling."""
        try:
            stance = Stance(stance_hint)
        except ValueError:
            stance = Stance.NEUTRAL
        # Strength: 0 for empty, ramps up with evidence, capped at 1
        if not evidence:
            base = 0.3
        else:
            base = min(1.0, 0.4 + 0.15 * len(evidence))
        # Stronger opinion if we have lots of evidence
        if len(evidence) >= MIN_EVIDENCE_FOR_STRONG_OPINION:
            base = max(base, 0.6)
        return stance, base

    def to_dict(self) -> Dict[str, str]:
        return {topic: op.to_dict() for topic, op in self.opinions.items()}


__all__ = ["OpinionSystem", "Opinion", "Stance"]
