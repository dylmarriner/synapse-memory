"""Temporal knowledge graph: subject-predicate-object triples with validity
windows.

A triple says "S P O" and is true between `valid_from` and `valid_to`.  An
open-ended fact has `valid_to = None`.  A contradiction is handled by
closing the old fact (set `valid_to = now`) and inserting a new open-ended
one.  This is the standard "temporal bi-temporal" model and it lets the
graph answer "what was true at time T?" with a single SQL filter.

The graph is intentionally minimal — no inference, no probabilistic
reasoning, no schema.  Just triples with valid_from / valid_to.  The
ingestion pipeline produces triples from extracted facts; the recall
pipeline queries them with an `as_of` filter.

Time is stored as ISO 8601 strings so the table is portable.  Datetime
objects are accepted on the way in and converted; queries accept either
strings or dates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_VALID_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z")


def _coerce(value: Any) -> str:
    """Coerce a date/datetime/ISO string into a normalized ISO 8601 string."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        for fmt in _VALID_FORMATS:
            try:
                dt = datetime.strptime(value, fmt)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        raise ValueError(f"unparseable date: {value!r}")
    raise TypeError(f"cannot coerce {type(value).__name__} to ISO date")


def _parse(value: str) -> datetime:
    """Parse a normalized ISO 8601 string into a tz-aware datetime."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"bad temporal string: {value!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class Triple:
    """A single fact in the temporal knowledge graph."""
    subject: str
    predicate: str
    object: str
    valid_from: Optional[str] = None  # ISO 8601; None = "from the beginning of time"
    valid_to: Optional[str] = None    # ISO 8601; None = "still true / open-ended"
    confidence: float = 1.0
    source: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.subject or not self.predicate or not self.object:
            raise ValueError("triple requires subject, predicate, and object")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")
        if self.valid_from and self.valid_to:
            if _parse(self.valid_to) < _parse(self.valid_from):
                raise ValueError(
                    f"inverted interval: valid_to ({self.valid_to}) "
                    f"< valid_from ({self.valid_from})"
                )

    def is_open(self) -> bool:
        """True if this triple has no end-date — i.e. it's still believed true."""
        return self.valid_to is None

    def is_valid_at(self, as_of: Any) -> bool:
        """True if this triple's interval covers `as_of`."""
        t = _coerce(as_of)
        if self.valid_from and _parse(t) < _parse(self.valid_from):
            return False
        if self.valid_to and _parse(t) >= _parse(self.valid_to):
            return False
        return True


@dataclass
class TemporalGraph:
    """A minimal in-memory temporal triple store.

    Use this as the in-process backing for the agent's working knowledge
    graph.  The same `Triple` shape can be persisted to SQL by mapping
    fields to columns; see `to_row()` and `from_row()`.
    """
    triples: List[Triple] = field(default_factory=list)

    def add(self, triple: Triple) -> Triple:
        """Append a triple.  Call `close_contradictions()` to handle overlap."""
        self.triples.append(triple)
        return triple

    def extend(self, triples: Iterable[Triple]) -> int:
        before = len(self.triples)
        for t in triples:
            self.add(t)
        return len(self.triples) - before

    def close_contradictions(
        self,
        subject: str,
        predicate: str,
        closed_at: Optional[Any] = None,
    ) -> int:
        """Close all open-ended triples that match (subject, predicate).

        A new triple can then be inserted to represent the contradicting
        fact.  Returns the number of triples closed.
        """
        closed_at_str = _coerce(closed_at) if closed_at else _coerce(datetime.now(timezone.utc))
        n = 0
        for i, t in enumerate(self.triples):
            if t.subject == subject and t.predicate == predicate and t.is_open():
                self.triples[i] = Triple(
                    subject=t.subject,
                    predicate=t.predicate,
                    object=t.object,
                    valid_from=t.valid_from,
                    valid_to=closed_at_str,
                    confidence=t.confidence,
                    source=t.source,
                )
                n += 1
        return n

    def query(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object: Optional[str] = None,
        as_of: Any = None,
    ) -> List[Triple]:
        """Return triples matching the filter, optionally time-clamped."""
        results: List[Triple] = []
        for t in self.triples:
            if subject is not None and t.subject != subject:
                continue
            if predicate is not None and t.predicate != predicate:
                continue
            if object is not None and t.object != object:
                continue
            if as_of is not None and not t.is_valid_at(as_of):
                continue
            results.append(t)
        return results

    def query_entity(
        self,
        name: str,
        *,
        as_of: Any = None,
        direction: str = "outgoing",
    ) -> List[Triple]:
        """Return every triple where `name` is the subject and/or object.

        direction:
          "outgoing" - only triples where name is the subject
          "incoming" - only triples where name is the object
          "both"     - either side
        """
        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(f"direction must be outgoing|incoming|both, got {direction!r}")
        out: List[Triple] = []
        for t in self.triples:
            if as_of is not None and not t.is_valid_at(as_of):
                continue
            if direction in ("outgoing", "both") and t.subject == name:
                out.append(t)
            if direction in ("incoming", "both") and t.object == name:
                out.append(t)
        return out

    def to_rows(self) -> List[Dict[str, Any]]:
        """Serialize to a list of dicts (suitable for SQL INSERT)."""
        return [
            {
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "valid_from": t.valid_from,
                "valid_to": t.valid_to,
                "confidence": t.confidence,
                "source": t.source,
            }
            for t in self.triples
        ]

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> "TemporalGraph":
        g = cls()
        for r in rows:
            g.add(Triple(
                subject=r["subject"],
                predicate=r["predicate"],
                object=r["object"],
                valid_from=r.get("valid_from"),
                valid_to=r.get("valid_to"),
                confidence=float(r.get("confidence", 1.0) or 1.0),
                source=r.get("source"),
            ))
        return g


__all__ = [
    "Triple",
    "TemporalGraph",
    "_coerce",
]
