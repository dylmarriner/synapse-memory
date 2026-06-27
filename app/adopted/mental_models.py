"""Biomimetic memory organization: world / experiences / mental_models.

The brain does not store facts in one undifferentiated pool.  It separates
them by *what kind of thing* is being remembered:

- **world**            — facts about the world ("the stove gets hot",
  "the Eiffel Tower is in Paris").  These are external and true regardless
  of who the agent is.

- **experiences**      — events the agent lived through ("I touched the
  stove and it really hurt", "I met Alice in the office on Tuesday").
  These are first-person and bound to time.

- **mental_models**    — higher-order summaries that the agent has built
  from raw facts and experiences ("Alice prefers async communication",
  "the auth module is a frequent source of bugs").  These are the
  agent's working theories about the world.

The classification helps on three axes:

- **Recall precision** : a query like "what does the user prefer?" goes
  to mental_models first; a query like "what happened on Tuesday?"
  goes to experiences first.
- **Storage lifecycle** : world facts have very slow decay (geography
  rarely changes), experiences decay faster, mental_models can be
  re-derived from the underlying facts so they can be discarded and
  rebuilt.
- **Auditability** : "where did you get that from?" is a meaningful
  question — the agent can point to the experiences that produced a
  mental_model.

This module defines the three types, the `classify()` heuristic, the
`merge_into_mental_model()` aggregator, and a tiny in-memory store.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


class MentalModelKind(str, Enum):
    """The three biomimetic memory types."""
    WORLD         = "world"
    EXPERIENCE    = "experience"
    MENTAL_MODEL  = "mental_model"


# Heuristic triggers — used by `classify()` when the caller doesn't pass
# an explicit kind.  Tuned for English; other languages can subclass.
_WORLD_MARKERS = (
    "is a", "are a", "is an", "are an", "is the", "are the",
    "is located", "is part of", "is known as", "consists of",
    "contains", "is measured", "equals", "is defined as",
)
_EXPERIENCE_MARKERS = (
    "yesterday", "today", "this morning", "last week", "last month",
    "i did", "i went", "i met", "i saw", "i ran", "i built", "i fixed",
    "we did", "we met", "we built", "we deployed", "we shipped",
    "happened", "occurred", "took place",
)
_MENTAL_MODEL_MARKERS = (
    "i think", "i believe", "i feel", "i prefer", "i usually",
    "the pattern is", "in my experience", "tends to", "generally",
    "prefers", "always", "never", "rarely",
)


def classify(text: str, *, hint: Optional[MentalModelKind] = None) -> MentalModelKind:
    """Classify a memory into one of the three biomimetic kinds.

    If `hint` is given, return it.  Otherwise score the text against the
    marker lists; the highest scoring kind wins, with `world` as the
    fallback.
    """
    if hint is not None:
        return hint
    low = text.lower()
    w = sum(1 for m in _WORLD_MARKERS if m in low)
    e = sum(1 for m in _EXPERIENCE_MARKERS if m in low)
    m = sum(1 for mk in _MENTAL_MODEL_MARKERS if mk in low)
    if m > w and m > e:
        return MentalModelKind.MENTAL_MODEL
    if e > w:
        return MentalModelKind.EXPERIENCE
    return MentalModelKind.WORLD


@dataclass
class BiomimeticMemory:
    """A single memory item, classified by kind."""
    id: str
    text: str
    kind: MentalModelKind
    source_memory_ids: List[str] = field(default_factory=list)   # for mental_models
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def explain(self) -> str:
        """One-line explanation of how this memory was derived."""
        if self.kind == MentalModelKind.MENTAL_MODEL and self.source_memory_ids:
            return f"Mental model derived from {len(self.source_memory_ids)} source memories"
        return f"{self.kind.value} fact"


# ---- Aggregate ---------------------------------------------------------

def merge_into_mental_model(
    sources: Sequence[BiomimeticMemory],
    *,
    statement: str,
    confidence: float = 0.8,
    metadata: Optional[Mapping[str, Any]] = None,
) -> BiomimeticMemory:
    """Combine several world facts and experiences into one mental_model.

    The `statement` is the agent's higher-order claim; the `sources` are
    the underlying facts it generalises.
    """
    if not sources:
        raise ValueError("cannot merge zero source memories into a mental model")
    return BiomimeticMemory(
        id=str(uuid.uuid4()),
        text=statement,
        kind=MentalModelKind.MENTAL_MODEL,
        source_memory_ids=[s.id for s in sources],
        confidence=confidence,
        metadata=dict(metadata or {}),
    )


# ---- Store -------------------------------------------------------------

class BiomimeticStore(abc.ABC):
    """The storage surface for biomimetic memories."""

    @abc.abstractmethod
    def add(self, memory: BiomimeticMemory) -> None: ...

    @abc.abstractmethod
    def by_kind(self, kind: MentalModelKind, *, limit: int = 50) -> List[BiomimeticMemory]: ...

    @abc.abstractmethod
    def all(self, *, limit: int = 100) -> List[BiomimeticMemory]: ...


class InMemoryBiomimeticStore(BiomimeticStore):
    """A trivial store useful for tests and the embedded demo."""

    def __init__(self) -> None:
        self._items: Dict[str, BiomimeticMemory] = {}

    def add(self, memory: BiomimeticMemory) -> None:
        self._items[memory.id] = memory

    def by_kind(self, kind: MentalModelKind, *, limit: int = 50) -> List[BiomimeticMemory]:
        return [m for m in self._items.values() if m.kind == kind][:limit]

    def all(self, *, limit: int = 100) -> List[BiomimeticMemory]:
        return list(self._items.values())[:limit]


# ---- Routing -----------------------------------------------------------

def route_query(
    query: str,
    store: BiomimeticStore,
) -> Dict[MentalModelKind, List[BiomimeticMemory]]:
    """Pick the right kind(s) to search based on the query, then fetch.

    Heuristic routing:
      - questions about preferences / patterns  -> mental_models
      - questions about "when" / "who did"      -> experiences
      - questions about "what is" / "where is"   -> world
      - everything else                          -> mental_models first, then world
    """
    low = query.lower().strip()
    if any(mk in low for mk in ("prefer", "pattern", "tends to", "usually", "always")):
        return {MentalModelKind.MENTAL_MODEL: store.by_kind(MentalModelKind.MENTAL_MODEL)}
    if any(mk in low for mk in ("when", "happened", "did", "was", "last", "yesterday", "today")):
        return {MentalModelKind.EXPERIENCE: store.by_kind(MentalModelKind.EXPERIENCE)}
    if any(mk in low for mk in ("what is", "where is", "who is", "how many", "how much")):
        return {MentalModelKind.WORLD: store.by_kind(MentalModelKind.WORLD)}
    return {
        MentalModelKind.MENTAL_MODEL: store.by_kind(MentalModelKind.MENTAL_MODEL),
        MentalModelKind.WORLD: store.by_kind(MentalModelKind.WORLD),
    }


__all__ = [
    "MentalModelKind",
    "BiomimeticMemory",
    "classify",
    "merge_into_mental_model",
    "BiomimeticStore",
    "InMemoryBiomimeticStore",
    "route_query",
]
