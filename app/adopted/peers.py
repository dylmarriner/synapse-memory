"""Peer-centric memory: every participant is a Peer, observations are
keyed by (observer, observed) pair.

In a multi-agent system, a useful piece of information is rarely about
the world in the abstract — it is about *how one agent sees another*.

The peer model says: every participant (a human, an AI agent, an
external system) is a `Peer`.  Every observation is a triple
`(observer, observed, content)`.  "Alice is a senior engineer" is
Alice's self-representation.  "Alice prefers dark mode" is
Nora's representation of Alice.  The same fact, observed by two
different peers, is two distinct observations.

This buys three things:

- **Plural perspectives** : two peers can disagree about a third peer
  and the system stores both views faithfully.
- **Scoped recall**        : "what does Nora think about Alice?" is a
  single endpoint call, not a query against a flat fact table.
- **Peer portability**     : a peer's representation can be exported
  and transferred to another agent unchanged.

This module defines the data model and an in-memory store.  The
production storage layer is an SQL view keyed on the (observer,
observed, workspace) triple with a unique constraint preventing
duplicates.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


class PeerKind(str, Enum):
    """What kind of participant this peer is."""
    HUMAN      = "human"
    AGENT      = "agent"
    SYSTEM     = "system"
    EXTERNAL   = "external"


@dataclass
class Peer:
    """A single participant in the system."""
    id: str
    name: str
    kind: PeerKind = PeerKind.AGENT
    workspace: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Peer.id is required")
        if not self.name:
            raise ValueError("Peer.name is required")


@dataclass
class PeerObservation:
    """A single fact one peer holds about another (or about itself)."""
    id: str
    observer: str          # the Peer.id of the observer
    observed: str          # the Peer.id of the observed
    text: str
    confidence: float = 1.0
    session: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("PeerObservation.text is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")


def pair_key(observer: str, observed: str, workspace: Optional[str] = None) -> Tuple[Optional[str], str, str]:
    """The canonical key for a peer-pair collection."""
    return (workspace, observer, observed)


# ---- Store ------------------------------------------------------------

class PeerStore(abc.ABC):
    """A two-dimensional store: peers, and observations keyed by pairs."""

    @abc.abstractmethod
    def upsert_peer(self, peer: Peer) -> Peer: ...

    @abc.abstractmethod
    def get_peer(self, peer_id: str, *, workspace: Optional[str] = None) -> Optional[Peer]: ...

    @abc.abstractmethod
    def list_peers(self, *, workspace: Optional[str] = None) -> List[Peer]: ...

    @abc.abstractmethod
    def add_observation(self, obs: PeerObservation) -> PeerObservation: ...

    @abc.abstractmethod
    def observations_about(
        self,
        observed: str,
        *,
        observer: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[PeerObservation]: ...

    @abc.abstractmethod
    def observations_by(
        self,
        observer: str,
        *,
        observed: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[PeerObservation]: ...


class InMemoryPeerStore(PeerStore):
    """A pure-Python PeerStore for tests and the embedded demo.

    Mirrors the SQL schema: observations are bucketed by
    (workspace, observer, observed) and the (observer, observed) pair
    is unique per workspace.
    """

    def __init__(self) -> None:
        self._peers: Dict[str, Peer] = {}
        self._observations: Dict[Tuple, List[PeerObservation]] = {}

    def upsert_peer(self, peer: Peer) -> Peer:
        if peer.id in self._peers:
            existing = self._peers[peer.id]
            peer = Peer(
                id=existing.id,
                name=peer.name or existing.name,
                kind=peer.kind or existing.kind,
                workspace=peer.workspace or existing.workspace,
                metadata={**existing.metadata, **peer.metadata},
                created_at=existing.created_at,
            )
        self._peers[peer.id] = peer
        return peer

    def get_peer(self, peer_id: str, *, workspace: Optional[str] = None) -> Optional[Peer]:
        peer = self._peers.get(peer_id)
        if peer is None:
            return None
        if workspace and peer.workspace and peer.workspace != workspace:
            return None
        return peer

    def list_peers(self, *, workspace: Optional[str] = None) -> List[Peer]:
        if workspace is None:
            return list(self._peers.values())
        return [p for p in self._peers.values() if p.workspace == workspace]

    def add_observation(self, obs: PeerObservation) -> PeerObservation:
        obs = PeerObservation(
            id=obs.id or str(uuid.uuid4()),
            observer=obs.observer,
            observed=obs.observed,
            text=obs.text,
            confidence=obs.confidence,
            session=obs.session,
            created_at=obs.created_at or datetime.now(timezone.utc),
            metadata=dict(obs.metadata),
        )
        key = pair_key(obs.observer, obs.observed, self._peers.get(obs.observer).workspace if obs.observer in self._peers else None)
        self._observations.setdefault(key, []).append(obs)
        return obs

    def observations_about(
        self,
        observed: str,
        *,
        observer: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[PeerObservation]:
        out: List[PeerObservation] = []
        for (ws, ob, od), obs_list in self._observations.items():
            if od != observed:
                continue
            if workspace and ws and ws != workspace:
                continue
            if observer and ob != observer:
                continue
            out.extend(obs_list)
        out.sort(key=lambda o: o.created_at, reverse=True)
        return out[:limit]

    def observations_by(
        self,
        observer: str,
        *,
        observed: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[PeerObservation]:
        out: List[PeerObservation] = []
        for (ws, ob, od), obs_list in self._observations.items():
            if ob != observer:
                continue
            if workspace and ws and ws != workspace:
                continue
            if observed and od != observed:
                continue
            out.extend(obs_list)
        out.sort(key=lambda o: o.created_at, reverse=True)
        return out[:limit]


# ---- Composition helpers ---------------------------------------------

def self_view(peer: Peer) -> Tuple[str, str]:
    """The (observer, observed) pair for a peer's self-representation."""
    return (peer.id, peer.id)


__all__ = [
    "PeerKind",
    "Peer",
    "PeerObservation",
    "PeerStore",
    "InMemoryPeerStore",
    "pair_key",
    "self_view",
]
