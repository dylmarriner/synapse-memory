"""Verbatim closet — a compact pointer layer over a drawer store.

A *closet* is a thin topic index that points back to the underlying
*drawers* (raw memory items).  It is *not* a summary — it is a pointer.

The format of a single closet line is:

    topic|entities|→drawer_id[,drawer_id2,...]

Multiple closet lines are packed into a single string up to a character
budget.  Closets are stored separately from the drawers themselves, so
they are easy to refresh, easy to version, and easy to ship as a
compressed "memory snapshot" of the agent.

The two main uses of a closet:

1. **Search-time rerank signal** — when a query hits a closet line
   pointing to drawer X, the ordinal position of the hit adds a fixed
   boost to X's vector score.  Closet rank 0 -> +0.40, rank 1 -> +0.25,
   rank 2 -> +0.15, rank 3 -> +0.08, rank 4 -> +0.04.  The boost is
   capped by a cosine-distance ceiling (1.5 by default) so a weak
   closet hit never overpowers a strong vector match.

2. **Indexing snapshot** — a full closet of the agent's state can be
   rendered in a few hundred tokens, suitable for inclusion in a
   system prompt as a "what I know" summary.

This module is pure-Python: it knows nothing about ChromaDB or any other
storage.  Pass it a list of `(drawer_id, content, metadata)` tuples and
it produces a closet.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---- Tunables ------------------------------------------------------------

CLOSET_CHAR_LIMIT: int = 1500
CLOSET_EXTRACT_WINDOW: int = 5000
CLOSET_MAX_TOPICS: int = 12
CLOSET_MAX_QUOTES: int = 3
CLOSET_SUMMARY_CHARS: int = 200

# Rank-based boost: a closet hit at rank 0 adds the largest boost, then
# rank 1, etc.  Cosine distance is *subtracted*, so this raises the
# effective similarity.
CLOSET_RANK_BOOSTS: Tuple[float, ...] = (0.40, 0.25, 0.15, 0.08, 0.04)
CLOSET_DISTANCE_CAP: float = 1.5

# The 2-3-drawer pointer window per closet line.
CLOSET_DRAWER_REF_MAX: int = 3


# ---- Data shape ---------------------------------------------------------

@dataclass
class DrawerRef:
    """The metadata of a single drawer, in the form a closet needs."""
    id: str
    content: str
    wing: str = "default"
    room: Optional[str] = None


@dataclass
class ClosetLine:
    """One pipe-separated line in a closet."""
    topic: str
    entities: str
    locator: Optional[str] = None
    drawer_refs: Tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        head = self.topic
        if self.entities:
            head = f"{head}|{self.entities}"
        if self.locator:
            head = f"{head}|{self.locator}"
        return f"{head}\u2192{','.join(self.drawer_refs)}"


# ---- Construction -------------------------------------------------------

# Cheap regex extractors — used when no LLM is available.
_TOPIC_RE = re.compile(
    r"(?:built|fixed|wrote|added|pushed|tested|created|shipped|designed|migrated|"
    r"refactored|deployed|merged|reviewed|debugged|optimized|investigated|"
    r"implemented|configured|updated)\s+[\w\s]{3,40}",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(r"^#{1,3}\s+(.{5,60})$", re.MULTILINE)
_QUOTE_RE = re.compile(r'"([^"]{15,150})"')


def _extract_topics(content: str) -> List[str]:
    window = content[:CLOSET_EXTRACT_WINDOW]
    found: List[str] = []
    seen: set = set()
    for pattern in (_TOPIC_RE, _HEADER_RE):
        for m in pattern.finditer(window):
            t = m.group(0).strip().lower()
            if t and t not in seen:
                seen.add(t)
                found.append(t)
    return found[:CLOSET_MAX_TOPICS]


def _extract_quotes(content: str) -> List[str]:
    return _QUOTE_RE.findall(content[:CLOSET_EXTRACT_WINDOW])[:CLOSET_MAX_QUOTES]


def _extract_entities(content: str) -> str:
    """Comma-joined list of capitalised phrases (very naive)."""
    tokens: List[str] = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b", content):
        tokens.append(m.group(1).strip())
    seen: set = set()
    out: List[str] = []
    for t in tokens:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return ",".join(out[:8])


def build_closet_lines(
    drawer: DrawerRef,
    *,
    all_drawers: Optional[Sequence[DrawerRef]] = None,
    summary: Optional[str] = None,
) -> List[ClosetLine]:
    """Build the closet lines that point at this drawer.

    If `all_drawers` is supplied, the line's drawer_refs include up to
    CLOSET_DRAWER_REF_MAX related drawers (same wing+room).  This makes
    the closet a *pointer* into a small cluster, not a pointer to a
    single item.
    """
    related: List[str] = []
    if all_drawers is not None:
        for d in all_drawers:
            if d.id == drawer.id:
                continue
            if d.wing == drawer.wing and d.room == drawer.room:
                related.append(d.id)
    drawer_refs = tuple([drawer.id, *related[: CLOSET_DRAWER_REF_MAX - 1]])

    lines: List[ClosetLine] = []
    entities = _extract_entities(drawer.content)
    for topic in _extract_topics(drawer.content):
        lines.append(ClosetLine(
            topic=topic,
            entities=entities,
            drawer_refs=drawer_refs,
        ))
    for quote in _extract_quotes(drawer.content):
        lines.append(ClosetLine(
            topic=f'"{quote}"',
            entities=entities,
            drawer_refs=drawer_refs,
        ))
    if summary:
        lines.append(ClosetLine(
            topic=summary[:CLOSET_SUMMARY_CHARS],
            entities=entities,
            drawer_refs=drawer_refs,
        ))
    return lines


def build_closet(
    drawers: Sequence[DrawerRef],
    *,
    summaries: Optional[Dict[str, str]] = None,
    char_limit: int = CLOSET_CHAR_LIMIT,
) -> str:
    """Build a single packed-closet string from many drawers.

    Lines are packed greedily up to `char_limit`.  If the closet would
    exceed the limit, lines are truncated but never split (a closet
    line is an atomic unit).
    """
    out: List[str] = []
    used = 0
    for d in drawers:
        lines = build_closet_lines(d, all_drawers=drawers, summary=(summaries or {}).get(d.id))
        for line in lines:
            rendered = line.render()
            if used + len(rendered) + 1 > char_limit:
                return "\n".join(out)
            out.append(rendered)
            used += len(rendered) + 1
    return "\n".join(out)


# ---- Rerank ------------------------------------------------------------

def apply_closet_boost(
    *,
    drawer_id: str,
    drawer_distance: float,
    closet_rank: int,
) -> float:
    """Subtract the rank-based boost from the drawer's cosine distance.

    `closet_rank` is the 0-based rank of the closet hit that matched
    this drawer; ranks >= len(CLOSET_RANK_BOOSTS) get no boost.
    """
    if drawer_distance > CLOSET_DISTANCE_CAP:
        return drawer_distance
    if 0 <= closet_rank < len(CLOSET_RANK_BOOSTS):
        return max(0.0, drawer_distance - CLOSET_RANK_BOOSTS[closet_rank])
    return drawer_distance


def best_closet_rank(
    *,
    drawer_id: str,
    closet_lines: Sequence[ClosetLine],
) -> int:
    """Return the best (lowest-numbered) rank of a closet line that points
    to this drawer.  -1 if no closet line mentions it.
    """
    best = -1
    for rank, line in enumerate(closet_lines):
        if drawer_id in line.drawer_refs:
            best = rank
            break
    return best


__all__ = [
    "DrawerRef",
    "ClosetLine",
    "CLOSET_CHAR_LIMIT",
    "CLOSET_EXTRACT_WINDOW",
    "CLOSET_MAX_TOPICS",
    "CLOSET_MAX_QUOTES",
    "CLOSET_RANK_BOOSTS",
    "CLOSET_DISTANCE_CAP",
    "CLOSET_DRAWER_REF_MAX",
    "build_closet_lines",
    "build_closet",
    "apply_closet_boost",
    "best_closet_rank",
]
