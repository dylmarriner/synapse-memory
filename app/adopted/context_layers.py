"""4-layer progressive-disclosure context stack.

A *context stack* is a way of loading only as much memory as the model can
afford.  Four layers, from cheapest and most-abstract to most-expensive and
most-specific:

- L0  **Identity**    : a few hundred tokens, always loaded.  The agent's
  self-description, the user's name, the project's one-line summary.
  Drawn from a single file/table; never recomputed.

- L1  **Essential**   : 500-800 tokens, computed lazily.  A short narrative
  built from the top-N most-important, most-recent memories.  This is what
  the agent sees in its system prompt by default.

- L2  **On-demand**   : 200-500 tokens per call, scoped.  The user asks
  "what's in the auth module?" — the system pulls the relevant slice.

- L3  **Deep search** : unlimited.  Full vector + lexical + graph search
  over the entire store.  The user asks an open-ended question; the
  system returns the top-K and ranks them.

A `wake_up()` call returns the L0+L1 string — about 600-900 tokens total —
ready to be prepended to the system prompt.

A `recall(query)` call returns a Layer 2 string — the most relevant slice
of memory for the query, scoped by a wing/room if the caller passed one.

A `search(query)` call returns a Layer 3 string — the full semantic-search
result, with optional filter.

This module is pure-Python and does not know about any specific storage
backend.  The `Layer0` reads from a local file.  The other layers are
abstract — subclasses plug in ChromaDB / pgvector / Qdrant / whatever.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

LAYER0_DEFAULT_PATH = "~/.nexus/identity.txt"
LAYER1_MAX_DRAWERS = 15
LAYER1_MAX_CHARS = 3200
LAYER2_N_RESULTS = 10
LAYER3_N_RESULTS = 5


# ---- Layer 0: identity (always loaded) -------------------------------------

class Layer0:
    """A few hundred tokens.  Always loaded.  Static file or table."""

    def __init__(self, path: str = LAYER0_DEFAULT_PATH) -> None:
        self.path = os.path.expanduser(path)
        self._text: str = ""

    def load(self) -> str:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self._text = f.read().strip()
        return self._text

    def save(self, text: str) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text.strip())
        self._text = text.strip()

    def render(self) -> str:
        return self._text or self.load()


# ---- Layer 1: essential story (auto-generated top-N) ----------------------

class Layer1:
    """500-800 tokens.  The agent's 'what's been happening lately' summary.

    Scoring: prefer high importance, recent filing, frequent access.
    A subclass supplies `_candidate_drawers()` to enumerate the full set;
    this class then picks the top N.
    """

    def __init__(self) -> None:
        self.importance_floor: float = 0.3
        self.recent_filing_days: int = 30
        self.max_drawers: int = LAYER1_MAX_DRAWERS
        self.max_chars: int = LAYER1_MAX_CHARS

    def _candidate_drawers(self) -> List["Drawer"]:
        """Override in subclasses to return drawers from your storage."""
        return []

    def generate(self) -> str:
        drawers = self._candidate_drawers()
        scored: List[tuple] = []
        for d in drawers:
            score = self._score(d)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [d for _, d in scored[: self.max_drawers]]
        return self._format(top)

    @staticmethod
    def _score(d: "Drawer") -> float:
        score = float(d.importance)
        if d.access_count:
            score += min(0.3, 0.05 * d.access_count)
        return score

    def _format(self, top: Sequence["Drawer"]) -> str:
        if not top:
            return "(no essential story yet)"
        out: List[str] = []
        for d in top:
            scope = d.wing + (f".{d.room}" if d.room else "")
            line = f"- [{scope}] {d.preview}".strip()
            out.append(line[:280])
        text = "\n".join(out)
        return text[: self.max_chars]


# ---- Layer 2: on-demand slice (wing/room filtered) ------------------------

class Layer2(ABC):
    """200-500 tokens per call.  Wing/room filtered retrieval."""

    @abstractmethod
    def retrieve(
        self,
        *,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        n_results: int = LAYER2_N_RESULTS,
    ) -> str: ...


# ---- Layer 3: full semantic search -----------------------------------------

class Layer3(ABC):
    """Unlimited depth.  Pure semantic search."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        n_results: int = LAYER3_N_RESULTS,
    ) -> str: ...


# ---- Drawer: a single memory item ------------------------------------------

@dataclass
class Drawer:
    """One memory item, the atomic unit the layers operate over."""
    id: str
    content: str
    wing: str = "default"
    room: Optional[str] = None
    importance: float = 0.5
    access_count: int = 0
    created_at: Optional[str] = None
    last_accessed: Optional[str] = None

    @property
    def preview(self) -> str:
        # First non-empty line, truncated
        line = next((l for l in self.content.splitlines() if l.strip()), self.content)
        return line[:200].strip()


# ---- The stack -------------------------------------------------------------

@dataclass
class MemoryStack:
    """The full 4-layer stack.  One class, one agent, everything works."""
    l0: Layer0 = field(default_factory=Layer0)
    l1: Layer1 = field(default_factory=Layer1)
    l2: Optional[Layer2] = None
    l3: Optional[Layer3] = None

    def wake_up(self) -> str:
        """L0 + L1, ~600-900 tokens.  Inject into the system prompt."""
        return "\n".join([self.l0.render(), "", self.l1.generate()]).strip()

    def recall(
        self,
        *,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        n_results: int = LAYER2_N_RESULTS,
    ) -> str:
        if self.l2 is None:
            raise RuntimeError("no L2 backend wired")
        return self.l2.retrieve(wing=wing, room=room, n_results=n_results)

    def search(
        self,
        query: str,
        *,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        n_results: int = LAYER3_N_RESULTS,
    ) -> str:
        if self.l3 is None:
            raise RuntimeError("no L3 backend wired")
        return self.l3.search(query, wing=wing, room=room, n_results=n_results)


__all__ = [
    "Layer0",
    "Layer1",
    "Layer2",
    "Layer3",
    "Drawer",
    "MemoryStack",
    "LAYER0_DEFAULT_PATH",
    "LAYER1_MAX_DRAWERS",
    "LAYER1_MAX_CHARS",
    "LAYER2_N_RESULTS",
    "LAYER3_N_RESULTS",
]
