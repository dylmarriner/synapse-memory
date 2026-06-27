"""4-tier memory consolidation: working / episodic / semantic / procedural.

Every new memory starts in **working** tier — raw, uncompressed, ready to
be re-surfaced immediately.  Over time the consolidation process promotes
memories into progressively more abstract tiers:

    working      raw observation (a single turn, a single tool call)
        |
        v
    episodic     session summary / turn summary (compressed narrative)
        |
        v
    semantic     extracted fact (a single durable claim)
        |
        v
    procedural   how-to knowledge (a reusable procedure, step sequence)

The promotion criteria:

- working -> episodic : when a session ends, summarize the working
  memories into one or more episodic memories
- episodic -> semantic : when an episodic memory is reinforced across
  multiple sessions, extract the durable claim into a semantic memory
- episodic -> procedural : when the same sequence of steps appears
  repeatedly, promote to a procedural memory

Each tier has its own decay characteristics:

- working : decays fastest (half-life 1 day)
- episodic : half-life 7 days
- semantic : half-life 90 days
- procedural : never decays (only superseded)

This module is a pure-Python implementation.  Persistence is the
caller's job:  `tier` becomes a column on the `Memory` table; `promote()`
returns a new `Memory` with the new tier and a `promoted_at` timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class Tier(str, Enum):
    """The four consolidation tiers, in promotion order."""
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

    @classmethod
    def parse(cls, value: Any) -> "Tier":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            raise ValueError(f"unknown tier: {value!r}")


# Half-life per tier, in days.  None means "never decays".
HALF_LIFE_DAYS: Dict[Tier, Optional[float]] = {
    Tier.WORKING:    1.0,
    Tier.EPISODIC:   7.0,
    Tier.SEMANTIC:   90.0,
    Tier.PROCEDURAL: None,
}


# A "session" in the consolidation sense is a series of working memories
# from the same source within a short time window.  When that session
# ends, the working memories get summarized into one or more episodic
# memories, then removed (or marked) from the working pool.

DEFAULT_SESSION_GAP_SECONDS: int = 60 * 30  # 30 minutes of inactivity = end of session


@dataclass
class TieredMemory:
    """A memory annotated with its tier and promotion history."""
    id: str
    content: str
    tier: Tier = Tier.WORKING
    source_id: Optional[str] = None       # the memory this was promoted from
    promoted_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def promote(self, to: Tier) -> "TieredMemory":
        """Return a new TieredMemory at the next tier up."""
        if not _can_promote(self.tier, to):
            raise ValueError(
                f"cannot promote from {self.tier.value} to {to.value} "
                f"(must move in order: working -> episodic -> semantic -> procedural)"
            )
        return TieredMemory(
            id=self.id,
            content=self.content,
            tier=to,
            source_id=self.source_id or self.id,
            promoted_at=datetime.now(timezone.utc),
            created_at=self.created_at,
            tags=list(self.tags),
            metadata=dict(self.metadata),
        )

    def decay_strength(self, *, now: Optional[datetime] = None) -> float:
        """Return the current strength in [0, 1] for this tier at time `now`."""
        now = now or datetime.now(timezone.utc)
        half_life = HALF_LIFE_DAYS[self.tier]
        if half_life is None:
            return 1.0
        anchor = self.promoted_at or self.created_at
        if anchor is None:
            return 1.0
        days = max(0.0, (now - anchor).total_seconds() / 86400.0)
        # Exponential decay: strength = 0.5 ** (days / half_life)
        return 0.5 ** (days / half_life)


def _can_promote(frm: Tier, to: Tier) -> bool:
    order = [Tier.WORKING, Tier.EPISODIC, Tier.SEMANTIC, Tier.PROCEDURAL]
    return order.index(to) == order.index(frm) + 1


def is_promotable(tier: Tier) -> bool:
    """True if the tier can still be promoted to a higher tier."""
    return tier != Tier.PROCEDURAL


def next_tier(current: Tier) -> Optional[Tier]:
    """Return the next tier in the promotion chain, or None at the top."""
    if current == Tier.WORKING:
        return Tier.EPISODIC
    if current == Tier.EPISODIC:
        return Tier.SEMANTIC
    if current == Tier.SEMANTIC:
        return Tier.PROCEDURAL
    return None


def batch_working_to_episodic(
    session: List[TieredMemory],
    summary: str,
    *,
    now: Optional[datetime] = None,
) -> TieredMemory:
    """Compress a session's worth of working memories into one episodic memory.

    The caller is responsible for choosing the summary text — typically by
    calling an LLM with the joined content.  This function just packages
    the result.
    """
    if not session:
        raise ValueError("cannot consolidate an empty session")
    if any(m.tier != Tier.WORKING for m in session):
        raise ValueError("all session memories must be in the working tier")
    return TieredMemory(
        id=session[0].id,            # the first id; downstream may renumber
        content=summary,
        tier=Tier.EPISODIC,
        source_id=session[0].id,
        promoted_at=now or datetime.now(timezone.utc),
        created_at=session[0].created_at,
        tags=sorted({t for m in session for t in m.tags}),
        metadata={"consolidated_from": [m.id for m in session]},
    )


__all__ = [
    "Tier",
    "TieredMemory",
    "HALF_LIFE_DAYS",
    "DEFAULT_SESSION_GAP_SECONDS",
    "is_promotable",
    "next_tier",
    "batch_working_to_episodic",
]
