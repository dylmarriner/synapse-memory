"""Pluggable storage backend: a uniform contract over ChromaDB, Qdrant,
pgvector, or anything else.

Every backend implements the same `BaseCollection` and `BaseBackend`
interface, so call sites don't care which one they're talking to.  The
tradeoff is a small loss of expressiveness (no vendor-specific tricks),
gained in two places: tests can use a deterministic in-memory backend
and production can swap implementations with a one-line config change.

Two extras over the minimum contract:

- **Capability tokens** — backends advertise what they support
  (`supports_namespace_isolation`, `supports_metadata_filter`, etc.) so
  the caller can degrade gracefully on a backend that doesn't.
- **Embedder identity check** — a single helper that compares the
  embedding model the index was built with against the one the caller
  is asking for.  Mixing models silently corrupts vector search.
"""

from __future__ import annotations

import abc
import hashlib
import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---- Capability tokens ---------------------------------------------------

class Capability(str, Enum):
    """Tokens a backend can advertise as supported."""
    NAMESPACE_ISOLATION = "supports_namespace_isolation"
    METADATA_FILTER     = "supports_metadata_filter"
    FULL_TEXT_SEARCH    = "supports_full_text_search"
    HYBRID_SEARCH       = "supports_hybrid_search"
    DELETE_BY_FILTER    = "supports_delete_by_filter"
    BM25                = "supports_bm25"


# ---- Result types --------------------------------------------------------

@dataclass
class QueryHit:
    """A single hit from a `query()` call."""
    id: str
    score: float                       # 0..1, higher is better
    document: Optional[str] = None
    embedding: Optional[Sequence[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Result of a `query()` call."""
    hits: List[QueryHit] = field(default_factory=list)
    total: int = 0

    def __post_init__(self) -> None:
        if not self.total:
            self.total = len(self.hits)


@dataclass
class GetResult:
    """Result of a `get()` call."""
    items: List[Dict[str, Any]] = field(default_factory=list)   # raw payloads
    total: int = 0

    def __post_init__(self) -> None:
        if not self.total:
            self.total = len(self.items)


@dataclass
class MaintenanceResult:
    """Result of a `maintenance()` call.  Free-form metrics + outcome."""
    kind: str
    success: bool = True
    items_processed: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)


# ---- Per-collection surface ---------------------------------------------

class BaseCollection(abc.ABC):
    """Read/write surface for a single named collection.

    All methods are kwargs-only so call sites stay readable when the
    argument list grows.
    """

    name: str

    @abc.abstractmethod
    def add(
        self,
        *,
        documents: Sequence[str],
        ids: Sequence[str],
        metadatas: Optional[Sequence[Mapping[str, Any]]] = None,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
    ) -> None: ...

    @abc.abstractmethod
    def upsert(
        self,
        *,
        documents: Sequence[str],
        ids: Sequence[str],
        metadatas: Optional[Sequence[Mapping[str, Any]]] = None,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
    ) -> None: ...

    @abc.abstractmethod
    def query(
        self,
        *,
        query_texts: Optional[Sequence[str]] = None,
        query_embeddings: Optional[Sequence[Sequence[float]]] = None,
        n_results: int = 10,
        where: Optional[Mapping[str, Any]] = None,
        where_document: Optional[Mapping[str, Any]] = None,
        include: Optional[Sequence[str]] = None,
    ) -> QueryResult: ...

    @abc.abstractmethod
    def get(
        self,
        *,
        ids: Optional[Sequence[str]] = None,
        where: Optional[Mapping[str, Any]] = None,
        where_document: Optional[Mapping[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Optional[Sequence[str]] = None,
    ) -> GetResult: ...

    @abc.abstractmethod
    def delete(
        self,
        *,
        ids: Optional[Sequence[str]] = None,
        where: Optional[Mapping[str, Any]] = None,
    ) -> int: ...

    @abc.abstractmethod
    def count(self) -> int: ...


# ---- Backend factory ---------------------------------------------------

@dataclass
class BackendIdentity:
    """Stable fingerprint of a backend configuration.

    Includes the embedder name + a hash of the embedding dimension so
    silently swapping embedders can be detected.
    """
    backend_name: str
    embedder_name: str
    embedding_dim: int
    distance_metric: str = "cosine"

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(self.backend_name.encode())
        h.update(b"|")
        h.update(self.embedder_name.encode())
        h.update(b"|")
        h.update(str(self.embedding_dim).encode())
        h.update(b"|")
        h.update(self.distance_metric.encode())
        return h.hexdigest()


def check_embedder_identity(
    stored: Optional[BackendIdentity],
    current: BackendIdentity,
    *,
    force_model_swap: bool = False,
) -> str:
    """Three-state check: 'unknown' | 'known_match' | 'known_mismatch'."""
    if stored is None:
        return "unknown"
    if stored.fingerprint() == current.fingerprint():
        return "known_match"
    if force_model_swap:
        return "known_match"
    return "known_mismatch"


class BaseBackend(abc.ABC):
    """The factory.  Each backend subclass implements `get_collection`."""

    name: str = "abstract"
    spec_version: str = "1.0"
    capabilities: frozenset = frozenset()
    distance_metric: str = "cosine"
    maintenance_kinds: frozenset = frozenset()

    identity: BackendIdentity

    @abc.abstractmethod
    def get_collection(
        self,
        *,
        name: str,
        create: bool = False,
        options: Optional[Mapping[str, Any]] = None,
    ) -> BaseCollection: ...

    def supports(self, cap: Capability) -> bool:
        return cap in self.capabilities


# ---- In-memory backend (tests + embedded) -----------------------------

class InMemoryCollection(BaseCollection):
    """A pure-Python backend for tests and embedded use.

    Stores documents in a dict, computes cosine similarity over
    normalized embeddings.
    """

    def __init__(self, name: str, distance_metric: str = "cosine") -> None:
        self.name = name
        self._docs: Dict[str, Dict[str, Any]] = {}
        self._distance = distance_metric

    def add(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        for i, _id in enumerate(ids):
            self._docs[_id] = {
                "document": documents[i] if i < len(documents) else "",
                "metadata": dict(metadatas[i]) if metadatas and i < len(metadatas) else {},
                "embedding": list(embeddings[i]) if embeddings and i < len(embeddings) else None,
            }

    def upsert(self, *, documents, ids, metadatas=None, embeddings=None) -> None:
        for i, _id in enumerate(ids):
            if _id in self._docs:
                # merge
                if i < len(documents):
                    self._docs[_id]["document"] = documents[i]
                if metadatas and i < len(metadatas):
                    self._docs[_id]["metadata"].update(metadatas[i])
                if embeddings and i < len(embeddings):
                    self._docs[_id]["embedding"] = list(embeddings[i])
            else:
                self.add(
                    documents=documents, ids=[_id],
                    metadatas=[metadatas[i]] if metadatas else None,
                    embeddings=[embeddings[i]] if embeddings else None,
                )

    def query(
        self,
        *,
        query_texts=None, query_embeddings=None, n_results=10,
        where=None, where_document=None, include=None,
    ) -> QueryResult:
        if not query_embeddings and not query_texts:
            return QueryResult()
        if query_embeddings:
            qvecs = query_embeddings
        else:
            # For the in-memory backend, "text search" is unsupported;
            # produce zero-score hits so callers degrade gracefully.
            return QueryResult(hits=[QueryHit(id="", score=0.0)] * 0)
        scored: List[QueryHit] = []
        for q in qvecs:
            for _id, rec in self._docs.items():
                if rec["embedding"] is None:
                    continue
                if where and not _matches(rec["metadata"], where):
                    continue
                score = _cosine(q, rec["embedding"])
                scored.append(QueryHit(
                    id=_id,
                    score=score,
                    document=rec["document"],
                    embedding=rec["embedding"],
                    metadata=rec["metadata"],
                ))
        scored.sort(key=lambda h: h.score, reverse=True)
        return QueryResult(hits=scored[:n_results])

    def get(self, *, ids=None, where=None, where_document=None, limit=None, offset=None, include=None) -> GetResult:
        items: List[Dict[str, Any]] = []
        for _id, rec in self._docs.items():
            if ids and _id not in ids:
                continue
            if where and not _matches(rec["metadata"], where):
                continue
            items.append({"id": _id, **rec})
        if offset:
            items = items[offset:]
        if limit:
            items = items[:limit]
        return GetResult(items=items)

    def delete(self, *, ids=None, where=None) -> int:
        n = 0
        if ids:
            for _id in ids:
                if self._docs.pop(_id, None) is not None:
                    n += 1
        elif where:
            for _id in list(self._docs):
                if _matches(self._docs[_id]["metadata"], where):
                    self._docs.pop(_id, None)
                    n += 1
        return n

    def count(self) -> int:
        return len(self._docs)


class InMemoryBackend(BaseBackend):
    """The in-memory backend.  Useful for tests and the embedded CLI."""

    name = "in-memory"
    capabilities = frozenset({
        Capability.NAMESPACE_ISOLATION,
        Capability.METADATA_FILTER,
        Capability.DELETE_BY_FILTER,
    })
    maintenance_kinds = frozenset({"count"})

    def __init__(self, embedder_name: str = "test-embedder", embedding_dim: int = 8) -> None:
        self._collections: Dict[str, InMemoryCollection] = {}
        self.identity = BackendIdentity(
            backend_name=self.name,
            embedder_name=embedder_name,
            embedding_dim=embedding_dim,
            distance_metric=self.distance_metric,
        )

    def get_collection(self, *, name: str, create: bool = False, options=None) -> InMemoryCollection:
        if name not in self._collections:
            if not create:
                raise KeyError(f"collection {name!r} does not exist (create=True to create)")
            self._collections[name] = InMemoryCollection(name)
        return self._collections[name]

    def maintenance(self, kind: str) -> MaintenanceResult:
        if kind == "count":
            total = sum(c.count() for c in self._collections.values())
            return MaintenanceResult(kind=kind, items_processed=total, metrics={"collections": len(self._collections)})
        return MaintenanceResult(kind=kind, success=False, metrics={"error": f"unknown kind {kind!r}"})


# ---- helpers ------------------------------------------------------------

def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(x * x for x in b)) or 1e-12
    return dot / (na * nb)


def _matches(meta: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
    """Tiny `where` evaluator: equality + $in + $contains."""
    for k, v in where.items():
        actual = meta.get(k)
        if isinstance(v, dict):
            if "$in" in v and actual not in v["$in"]:
                return False
            if "$contains" in v and (actual is None or v["$contains"] not in actual):
                return False
        else:
            if actual != v:
                return False
    return True


__all__ = [
    "Capability",
    "QueryHit",
    "QueryResult",
    "GetResult",
    "MaintenanceResult",
    "BaseCollection",
    "BaseBackend",
    "BackendIdentity",
    "check_embedder_identity",
    "InMemoryCollection",
    "InMemoryBackend",
]
