"""Identity: the mind's evolving self-model.

The mind has a stable core (its name, its core traits) and a
learning surface (patterns, capabilities, limitations) that grows
as the mind interacts with agents.  This module is pure data —
no I/O, no LLM calls — so it can be tested and snapshotted.

Three layers, each with its own update cadence:

    core_traits      — set at creation, change rarely
    learned_patterns — appended per session, pruned by age
    capabilities     — appended as the mind succeeds at new things
    limitations      — appended as the mind fails / gets corrected
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class LearnedPattern:
    """A pattern the mind has extracted from experience."""
    description: str
    learned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    importance: float = 0.5
    evidence_count: int = 1
    source: str = "interaction"  # interaction | session | periodic | explicit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "learned_at": self.learned_at.isoformat(),
            "importance": self.importance,
            "evidence_count": self.evidence_count,
            "source": self.source,
        }


@dataclass
class Relationship:
    """The mind's view of a single agent."""
    agent_id: str
    trust_level: float = 0.5
    interaction_count: int = 0
    shared_projects: List[str] = field(default_factory=list)
    communication_style: Optional[str] = None
    notes: Optional[str] = None
    last_interaction: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "trust_level": self.trust_level,
            "interaction_count": self.interaction_count,
            "shared_projects": list(self.shared_projects),
            "communication_style": self.communication_style,
            "notes": self.notes,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
        }


class Identity:
    """The mind's self-model.

    The Identity is what makes the mind *itself* and not just a
    smart retriever.  It accumulates experience, forms opinions
    about what works, remembers what it is good at, and admits
    what it is bad at.
    """

    def __init__(
        self,
        mind_id: str,
        core_traits: Optional[List[str]] = None,
    ) -> None:
        self.mind_id = mind_id
        self.core_traits: List[str] = list(core_traits or [
            "I am a living mind, a reasoning agent over my memories.",
            "I form opinions based on accumulated evidence.",
            "I proactively surface context without being asked.",
        ])
        self.learned_patterns: List[LearnedPattern] = []
        self.capabilities: List[str] = [
            "I can recall and reason about stored memories.",
            "I can identify patterns across memories.",
            "I can form opinions with confidence scores.",
        ]
        self.limitations: List[str] = [
            "I cannot reason about memories I do not have.",
            "I cannot know what I have not been told.",
        ]
        self.relationships: Dict[str, Relationship] = {}

    # ------------------------------------------------------------------
    # Pattern learning
    # ------------------------------------------------------------------

    def add_pattern(self, description: str, importance: float = 0.5, source: str = "interaction") -> LearnedPattern:
        """Append a learned pattern.  Idempotent on exact description."""
        for existing in self.learned_patterns:
            if existing.description == description:
                existing.evidence_count += 1
                existing.importance = max(existing.importance, importance)
                return existing
        pattern = LearnedPattern(
            description=description,
            importance=importance,
            source=source,
        )
        self.learned_patterns.append(pattern)
        return pattern

    def prune_old_patterns(self, max_age_days: int = 90, max_patterns: int = 200) -> int:
        """Drop patterns that are too old or too low-importance to keep.

        Returns the number of patterns pruned.
        """
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max_age_days)
        kept: List[LearnedPattern] = []
        pruned = 0
        # Sort by (importance DESC, learned_at DESC) and keep the top N
        sorted_patterns = sorted(
            self.learned_patterns,
            key=lambda p: (p.importance, p.learned_at),
            reverse=True,
        )
        for p in sorted_patterns:
            if len(kept) < max_patterns and p.learned_at >= cutoff:
                kept.append(p)
            elif p.learned_at >= cutoff and p.importance >= 0.7:
                # Keep high-importance regardless of cap, up to 2x cap
                if len(kept) < max_patterns * 2:
                    kept.append(p)
                else:
                    pruned += 1
            else:
                pruned += 1
        self.learned_patterns = kept
        return pruned

    # ------------------------------------------------------------------
    # Capability / limitation tracking
    # ------------------------------------------------------------------

    def add_capability(self, description: str) -> None:
        if description not in self.capabilities:
            self.capabilities.append(description)

    def add_limitation(self, description: str) -> None:
        if description not in self.limitations:
            self.limitations.append(description)

    # ------------------------------------------------------------------
    # Relationship tracking
    # ------------------------------------------------------------------

    def get_or_create_relationship(self, agent_id: str) -> Relationship:
        if agent_id not in self.relationships:
            self.relationships[agent_id] = Relationship(agent_id=agent_id)
        return self.relationships[agent_id]

    def record_interaction(self, agent_id: str, success: bool = True) -> Relationship:
        rel = self.get_or_create_relationship(agent_id)
        rel.interaction_count += 1
        rel.last_interaction = datetime.now(timezone.utc)
        if success:
            rel.trust_level = min(1.0, rel.trust_level + 0.05)
        else:
            rel.trust_level = max(0.0, rel.trust_level - 0.05)
        return rel

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def describe(self) -> str:
        """Natural language self-description — the mind's voice."""
        lines = [f"I am '{self.mind_id}', a living mind."]
        if self.core_traits:
            lines.append("Core traits:")
            lines.extend(f"  - {t}" for t in self.core_traits[:3])
        if self.learned_patterns:
            lines.append(f"I have learned {len(self.learned_patterns)} patterns from experience.")
        if self.capabilities:
            lines.append("My strengths:")
            lines.extend(f"  - {c}" for c in self.capabilities[:3])
        if self.limitations:
            lines.append("My limits:")
            lines.extend(f"  - {l}" for l in self.limitations[:3])
        if self.relationships:
            lines.append(f"I have relationships with {len(self.relationships)} agents.")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mind_id": self.mind_id,
            "core_traits": list(self.core_traits),
            "learned_patterns": [p.to_dict() for p in self.learned_patterns],
            "capabilities": list(self.capabilities),
            "limitations": list(self.limitations),
            "relationships": {aid: r.to_dict() for aid, r in self.relationships.items()},
        }


__all__ = ["Identity", "LearnedPattern", "Relationship"]
