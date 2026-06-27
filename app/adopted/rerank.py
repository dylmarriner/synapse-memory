"""Two-stage retrieval: bi-encoder recall → cross-encoder rerank.

Single-stage vector search is fast but imprecise.  Two-stage search is
still fast on the first pass and much more precise on the second:

1. **Bi-encoder**  : embed the query and every document with the same
   model, take the top-K by dot product.  O(N) but with one matrix
   multiply — millisecond latency even on a million-vector index.

2. **Cross-encoder** : take the top-K from step 1 and feed (query,
   document) pairs through a model that was trained to score the
   relationship between them.  Much more accurate, much more expensive,
   so it only runs on the K finalists.

The typical K is 10 for the first stage and 50 for the second, but both
are configurable.  Below the cross-encoder, the hits are ordered by
bi-encoder distance; above it, they are ordered by the cross-encoder's
1 - score (cross-encoders tend to output a "this is *not* relevant"
score, so we invert).

This module ships an `IdentityCrossEncoder` that returns 0.0 for every
hit (i.e. it does no reranking) — a sane default in tests and in
deployments that have no cross-encoder model.  Wire your own by
implementing the `CrossEncoder` protocol.
"""

from __future__ import annotations

import abc
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol, Sequence


# ---- Bi-encoder ---------------------------------------------------------

class BiEncoder(Protocol):
    """Embeds a batch of strings into a 2D matrix of floats."""
    def embed(self, texts: Sequence[str]) -> List[List[float]]: ...


class IdentityBiEncoder:
    """A deterministic 8-dim embedder for tests.  Each token -> a 1-hot
    position in an 8-dim vector, summed.  Two texts that share a token
    will share a non-zero coordinate.

    Uses a stable hash (FNV-1a) so embeddings are reproducible across
    processes — the default Python `hash()` is randomised.
    """

    DIM = 8

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    @staticmethod
    def _stable_hash(s: str) -> int:
        h = 2166136261
        for ch in s.encode():
            h ^= ch
            h = (h * 16777619) & 0xFFFFFFFF
        return h

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.lower().split():
                v[self._stable_hash(tok) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1e-12
            out.append([x / n for x in v])
        return out


# ---- Cross-encoder ------------------------------------------------------

class CrossEncoder(Protocol):
    """Scores (query, document) pairs."""
    def predict(self, query: str, documents: Sequence[str]) -> List[float]: ...


class IdentityCrossEncoder:
    """A trivial reranker: returns 0.0 for every pair (no reranking)."""

    def predict(self, query: str, documents: Sequence[str]) -> List[float]:
        return [0.0] * len(documents)


class DotProductCrossEncoder:
    """A toy reranker: returns 1 - cosine(query, document).  Useful for
    end-to-end tests where you want the rerank pass to actually do
    something, but you don't have a real model.
    """

    def __init__(self, bi: BiEncoder) -> None:
        self._bi = bi

    def predict(self, query: str, documents: Sequence[str]) -> List[float]:
        if not documents:
            return []
        qvec = self._bi.embed([query])[0]
        dvecs = self._bi.embed(documents)
        out: List[float] = []
        for d in dvecs:
            if not d or not qvec:
                out.append(0.0)
                continue
            dot = sum(a * b for a, b in zip(qvec, d))
            out.append(max(0.0, min(1.0, dot)))
        return out


# ---- The two-stage orchestrator -----------------------------------------

@dataclass
class Hit:
    """One search hit, enriched with both stages of scoring."""
    id: str
    document: str
    bi_score: float                # 0..1, from bi-encoder
    cross_score: float = 0.0       # 0..1, from cross-encoder (0 if not reranked)
    metadata: dict = field(default_factory=dict)

    @property
    def combined(self) -> float:
        """The final score used for ranking.  Cross-encoder when present,
        otherwise the bi-encoder score."""
        if self.cross_score:
            return self.cross_score
        return self.bi_score


@dataclass
class TwoStageConfig:
    """Tuning knobs for the two-stage search."""
    first_stage_k: int = 50           # how many to keep after bi-encoder
    second_stage_k: int = 10          # how many to return after cross-encoder
    rerank: bool = True
    bi_encoder_timeout_s: float = 5.0
    cross_encoder_timeout_s: float = 10.0


@dataclass
class TwoStageResult:
    hits: List[Hit] = field(default_factory=list)
    bi_encoder_ms: float = 0.0
    cross_encoder_ms: float = 0.0

    def top(self, k: int) -> List[Hit]:
        return self.hits[:k]


class TwoStageSearch:
    """The two-stage pipeline.  Wire the corpus at construction time."""

    def __init__(
        self,
        *,
        corpus: Sequence[Any],                      # items with .id, .document, .metadata
        bi_encoder: BiEncoder,
        cross_encoder: Optional[CrossEncoder] = None,
        config: Optional[TwoStageConfig] = None,
    ) -> None:
        self._corpus = list(corpus)
        self._bi = bi_encoder
        self._cross = cross_encoder or IdentityCrossEncoder()
        self._cfg = config or TwoStageConfig()

    def search(self, query: str, *, k: Optional[int] = None) -> TwoStageResult:
        k = k or self._cfg.second_stage_k
        t0 = time.perf_counter()
        bi_vecs = self._bi.embed([query])
        corpus_vecs = self._bi.embed([c.document for c in self._corpus])
        bi_ms = (time.perf_counter() - t0) * 1000

        scored: List[Hit] = []
        for item, vec in zip(self._corpus, corpus_vecs):
            if not vec or not bi_vecs[0]:
                continue
            score = _cosine(bi_vecs[0], vec)
            scored.append(Hit(
                id=getattr(item, "id", ""),
                document=item.document,
                bi_score=score,
                metadata=getattr(item, "metadata", {}) or {},
            ))
        scored.sort(key=lambda h: h.bi_score, reverse=True)
        first_stage = scored[: max(k, self._cfg.first_stage_k)]

        if not self._cfg.rerank or self._cross is None:
            result = TwoStageResult(
                hits=sorted(first_stage, key=lambda h: h.bi_score, reverse=True)[:k],
                bi_encoder_ms=bi_ms,
            )
            return result

        t0 = time.perf_counter()
        cross_scores = self._cross.predict(query, [h.document for h in first_stage])
        cross_ms = (time.perf_counter() - t0) * 1000
        for h, c in zip(first_stage, cross_scores):
            h.cross_score = float(c) if c is not None else 0.0
        first_stage.sort(key=lambda h: h.combined, reverse=True)
        return TwoStageResult(hits=first_stage[:k], bi_encoder_ms=bi_ms, cross_encoder_ms=cross_ms)


# ---- helpers ------------------------------------------------------------

def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(x * x for x in b)) or 1e-12
    return dot / (na * nb)


# Convenience item shape for the corpus.
@dataclass
class CorpusItem:
    id: str
    document: str
    metadata: dict = field(default_factory=dict)


__all__ = [
    "BiEncoder",
    "IdentityBiEncoder",
    "CrossEncoder",
    "IdentityCrossEncoder",
    "DotProductCrossEncoder",
    "Hit",
    "TwoStageConfig",
    "TwoStageResult",
    "TwoStageSearch",
    "CorpusItem",
]
