"""Three-method memory API: retain / recall / reflect.

The whole memory system is reduced to three operations:

- `retain(content, ...)`  — store something the agent should remember
- `recall(query, ...)`    — surface the most relevant memories
- `reflect(query, ...)`   — synthesise new insights from existing memories

Each call returns a structured result the agent can branch on:

- `retain`  ->  {"id": "...", "memory": "the new fact", "event": "ADD"}
- `recall`  ->  {"results": [{"id": "...", "content": "...", "score": 0.91}, ...]}
- `reflect` ->  {"reflection": "...", "evidence": ["id-1", "id-2"]}

The implementation here is a pure-Python orchestration layer — a stable
shape that the search / extraction / graph backends can plug into without
the caller caring which one is which.

`reflect` is the only one of the three that is *generative*: it consumes
recalled memories and produces a new conclusion that did not exist before.
`retain` and `recall` are both conservation operations (store / fetch).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol


class TriMethodEvent(str, Enum):
    """The lifecycle event a memory can be tagged with."""
    ADD = "ADD"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    NONE = "NONE"


@dataclass
class RetainResult:
    """Result of a `retain` call."""
    id: str
    memory: str
    event: TriMethodEvent = TriMethodEvent.ADD
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallHit:
    """A single hit from a `recall` call."""
    id: str
    content: str
    score: float                # 0..1
    memory_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallResult:
    """Result of a `recall` call."""
    results: List[RecallHit]
    total: int = 0
    strategy: str = "hybrid"    # which recall strategy was used

    def __post_init__(self) -> None:
        if not self.total:
            self.total = len(self.results)


@dataclass
class ReflectResult:
    """Result of a `reflect` call — a synthesised conclusion."""
    reflection: str
    evidence: List[str] = field(default_factory=list)   # ids of memories that grounded this
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---- Pluggable backends ----------------------------------------------------

class RetainBackend(Protocol):
    def retain(self, content: str, *, metadata: Dict[str, Any]) -> RetainResult: ...


class RecallBackend(Protocol):
    def recall(self, query: str, *, limit: int, filters: Optional[Dict[str, Any]]) -> RecallResult: ...


class ReflectBackend(Protocol):
    def reflect(self, query: str, *, evidence: List[RecallHit], filters: Optional[Dict[str, Any]]) -> ReflectResult: ...


# ---- Orchestrator ---------------------------------------------------------

class TriMethodMemory:
    """A facade that lets callers speak retain/recall/reflect without caring
    which backend is wired up.  Pass any combination of backends; missing
    methods raise NotImplementedError at call time.
    """

    def __init__(
        self,
        *,
        retain: Optional[RetainBackend] = None,
        recall: Optional[RecallBackend] = None,
        reflect: Optional[ReflectBackend] = None,
    ) -> None:
        self._retain = retain
        self._recall = recall
        self._reflect = reflect

    def retain(
        self,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        new_id: Optional[str] = None,
    ) -> RetainResult:
        if self._retain is None:
            raise NotImplementedError("no retain backend wired")
        meta = dict(metadata or {})
        if "id" not in meta and new_id:
            meta["id"] = new_id
        return self._retain.retain(content, metadata=meta)

    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RecallResult:
        if self._recall is None:
            raise NotImplementedError("no recall backend wired")
        return self._recall.recall(query, limit=limit, filters=filters)

    def reflect(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ReflectResult:
        if self._reflect is None:
            raise NotImplementedError("no reflect backend wired")
        # `reflect` always starts with a recall so it has evidence to ground on.
        if self._recall is None:
            raise NotImplementedError("reflect needs a recall backend to gather evidence")
        evidence = self._recall.recall(query, limit=limit, filters=filters).results
        return self._reflect.reflect(query, evidence=evidence, filters=filters)


# ---- Local in-memory implementation (handy for tests) -------------------

class InMemoryTriMethod:
    """Pure-Python tri-method implementation.  Useful for tests and demos.

    - retain:  appends to an in-memory list with a uuid
    - recall:  scores by simple token overlap (Jaccard) over the query
    - reflect: returns the joined top-3 recalled memories as the reflection

    This class implements the three backends separately so it can be
    used as building blocks of a `TriMethodMemory` (or on its own).
    """

    def __init__(self) -> None:
        self._items: List[RetainResult] = []

    def retain(self, content: str, *, metadata: Dict[str, Any]) -> RetainResult:
        meta = dict(metadata or {})
        rid = meta.pop("id", None) or str(uuid.uuid4())
        r = RetainResult(id=rid, memory=content, metadata=meta)
        self._items.append(r)
        return r

    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RecallResult:
        qtokens = _tokens(query)
        scored: List[RecallHit] = []
        for item in self._items:
            if filters and not _matches_filters(item.metadata, filters):
                continue
            score = _jaccard(qtokens, _tokens(item.memory))
            scored.append(RecallHit(
                id=item.id,
                content=item.memory,
                score=score,
                memory_type=item.metadata.get("memory_type"),
                metadata=item.metadata,
            ))
        scored.sort(key=lambda h: h.score, reverse=True)
        return RecallResult(results=scored[:limit], strategy="jaccard")

    def reflect(
        self,
        query: str,
        *,
        evidence: List[RecallHit],
        filters: Optional[Dict[str, Any]] = None,
    ) -> ReflectResult:
        joined = " | ".join(h.content for h in evidence[:3])
        confidence = sum(h.score for h in evidence[:3]) / max(1, min(3, len(evidence)))
        return ReflectResult(
            reflection=joined or "(no relevant memories)",
            evidence=[h.id for h in evidence[:3]],
            confidence=confidence,
        )


# A convenience facade that wires the three backends together.
def in_memory_tri_method() -> TriMethodMemory:
    """Build a `TriMethodMemory` backed by an in-memory store."""
    inner = InMemoryTriMethod()
    return TriMethodMemory(retain=inner, recall=inner, reflect=inner)


# ---- helpers ---------------------------------------------------------------

def _tokens(s: str) -> set:
    return {t.lower() for t in s.split() if t.strip()}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _matches_filters(meta: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    for k, v in filters.items():
        if meta.get(k) != v:
            return False
    return True


__all__ = [
    "TriMethodEvent",
    "RetainResult",
    "RecallHit",
    "RecallResult",
    "ReflectResult",
    "RetainBackend",
    "RecallBackend",
    "ReflectBackend",
    "TriMethodMemory",
    "InMemoryTriMethod",
]
