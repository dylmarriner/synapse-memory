"""Background deriver worker: batch messages, one LLM call per batch.

Memory writes are fast (one DB INSERT per memory).  Memory *reasoning* is
slow (an LLM call that produces structured observations).  These two
concerns must not be on the same code path — the user should not wait
for the LLM call to land before their save returns.

A `DeriverWorker` solves this with three pieces:

1. **Queue**        : an in-process or out-of-process job queue.  The save
   path enqueues a "deriver task" with the memory id, then returns.  The
   task payload is small: a memory id, an actor, an observer list.

2. **Batch consumer**: a worker that drains the queue.  It groups N tasks
   into a batch, fetches the underlying messages, makes **one** LLM call
   per batch, and writes the resulting observations to every observer's
   collection.

3. **Observation sink**: where the resulting observations land.  Typically
   a (observer, observed) key in a vector store — i.e. a per-peer-pair
   collection of derived facts about how one peer sees another.

This module defines the queue task types and the consumer's batch
dispatch — the LLM call itself is up to the caller, so any model works.
The whole thing is async-first; backpressure and timeouts are explicit.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger("nexus.adopted.deriver")


# ---- Task types ----------------------------------------------------------

class TaskType(str, Enum):
    """The five kinds of deriver tasks."""
    REPRESENTATION  = "representation"   # extract observations from messages
    SUMMARY         = "summary"          # summarize a session
    DREAM           = "dream"            # cross-session synthesis
    RECONCILER      = "reconciler"       # resolve contradictions
    WEBHOOK         = "webhook"          # deliver an external event
    DELETION        = "deletion"         # cascade-delete


@dataclass
class QueueItem:
    """A typed payload enqueued for the deriver worker."""
    id: str
    task_type: TaskType
    workspace: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0
    last_error: Optional[str] = None


# ---- Observation sink (output) ------------------------------------------

@dataclass
class Observation:
    """A single fact extracted by the deriver."""
    text: str
    memory_ids: List[str] = field(default_factory=list)
    confidence: float = 1.0
    explicit: bool = True
    deductive: bool = False
    source_session: Optional[str] = None


class ObservationSink(abc.ABC):
    """Where the deriver writes its output.

    Implementations:
      - InMemoryObservationSink (tests, demos)
      - NexusPeerCollectionSink (production — writes to (observer, observed) pair)
    """

    @abc.abstractmethod
    async def write(
        self,
        observations: List[Observation],
        *,
        observer: str,
        observed: str,
        workspace: Optional[str] = None,
    ) -> int:
        """Persist observations.  Returns the number actually written."""


class InMemoryObservationSink(ObservationSink):
    def __init__(self) -> None:
        self.buckets: Dict[tuple, List[Observation]] = {}

    async def write(
        self,
        observations: List[Observation],
        *,
        observer: str,
        observed: str,
        workspace: Optional[str] = None,
    ) -> int:
        key = (workspace or "_", observer, observed)
        self.buckets.setdefault(key, []).extend(observations)
        return len(observations)


# ---- LLM caller (inject your own) ----------------------------------------

LLMCaller = Callable[[str, List[Dict[str, Any]]], Awaitable[str]]


async def default_llm_caller(system: str, user: List[Dict[str, Any]]) -> str:
    """The default LLM caller is a no-op.  Wire your own in production."""
    log.warning("deriver: no LLM caller wired; returning empty response")
    return ""


# ---- Minimal deriver prompt -----------------------------------------------

def minimal_deriver_prompt(peer_id: str, messages: List[str]) -> str:
    """The prompt template used to extract explicit facts about a peer.

    Atomic, evidence-bound.  Returns a JSON list of observations.
    """
    formatted = "\n".join(f"- {m}" for m in messages)
    return (
        "You are extracting explicit, atomic facts about a single peer from "
        "their recent messages.\n"
        "DEFINITION: an explicit fact is a claim about the peer that can be "
        "derived directly from the message text, without inference.\n"
        "RULES:\n"
        "  - Use the exact peer id below, never 'the user' or 'the target peer'.\n"
        "  - Each fact must be self-contained — no implicit references.\n"
        "  - Return JSON: {\"observations\": [{\"text\": \"...\", \"confidence\": 0..1}, ...]}\n"
        f"Target peer: {peer_id}\n"
        f"Messages:\n{formatted}"
    )


# ---- Worker --------------------------------------------------------------

@dataclass
class DeriverWorker:
    """The background worker: drains the queue, batches, calls LLM, writes."""
    queue: "DeriverQueue"
    sink: ObservationSink
    llm_caller: LLMCaller = default_llm_caller
    batch_size: int = 16
    batch_window_seconds: float = 2.0
    max_attempts: int = 3

    async def run_once(self) -> int:
        """Drain one batch from the queue, return the number of items processed."""
        batch = await self.queue.take_batch(self.batch_size, self.batch_window_seconds)
        if not batch:
            return 0
        await self._process_batch(batch)
        return len(batch)

    async def run_forever(self) -> None:
        """Run as a long-lived task.  Cancelled by the surrounding event loop."""
        while True:
            await self.run_once()

    async def _process_batch(self, batch: List[QueueItem]) -> None:
        # Group by (task_type, workspace) so the LLM call can share context.
        groups: Dict[tuple, List[QueueItem]] = {}
        for item in batch:
            groups.setdefault((item.task_type, item.workspace), []).append(item)

        for (task_type, workspace), items in groups.items():
            for item in items:
                if item.attempts >= self.max_attempts:
                    log.warning("deriver: dropping %s after %d attempts", item.id, item.attempts)
                    continue
                try:
                    await self._process_item(item)
                    await self.queue.complete(item)
                except Exception as e:
                    item.attempts += 1
                    item.last_error = repr(e)
                    log.exception("deriver: failed to process %s", item.id)

    async def _process_item(self, item: QueueItem) -> None:
        if item.task_type == TaskType.REPRESENTATION:
            await self._do_representation(item)
        elif item.task_type == TaskType.SUMMARY:
            await self._do_summary(item)
        # Other task types plug in here.

    async def _do_representation(self, item: QueueItem) -> None:
        payload = item.payload
        peer_id: str = payload.get("peer_id", "")
        messages: List[str] = payload.get("messages", [])
        observers: List[str] = payload.get("observers") or [peer_id]
        if not peer_id or not messages:
            return
        prompt = minimal_deriver_prompt(peer_id, messages)
        raw = await self.llm_caller(prompt, [])
        observations = _parse_observations(raw)
        for observer in observers:
            await self.sink.write(
                observations,
                observer=observer,
                observed=peer_id,
                workspace=item.workspace,
            )

    async def _do_summary(self, item: QueueItem) -> None:
        # Hook for the summary task — a one-line plug-in.
        log.info("deriver: summary task %s not yet implemented", item.id)


def _parse_observations(raw: str) -> List[Observation]:
    """Parse the LLM response into a list of Observations.

    The format is `{"observations": [{"text": "...", "confidence": 0..1}, ...]}`.
    Errors are swallowed — the deriver never blocks on a bad parse.
    """
    import json
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out: List[Observation] = []
    for obs in (data.get("observations") or []):
        text = (obs.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(obs.get("confidence", 1.0) or 1.0)
        except (TypeError, ValueError):
            conf = 1.0
        out.append(Observation(text=text, confidence=conf))
    return out


# ---- Queue ---------------------------------------------------------------

class DeriverQueue(abc.ABC):
    """The queue the worker drains.

    `take_batch(size, window_seconds)` returns up to `size` items, waiting
    at most `window_seconds` for the first one to arrive.
    """

    @abc.abstractmethod
    async def put(self, item: QueueItem) -> None: ...

    @abc.abstractmethod
    async def take_batch(self, size: int, window_seconds: float) -> List[QueueItem]: ...

    @abc.abstractmethod
    async def complete(self, item: QueueItem) -> None: ...


class InMemoryDeriverQueue(DeriverQueue):
    """Trivial in-process queue for tests / single-process deployments."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._done: List[QueueItem] = []

    async def put(self, item: QueueItem) -> None:
        await self._q.put(item)

    async def take_batch(self, size: int, window_seconds: float) -> List[QueueItem]:
        batch: List[QueueItem] = []
        try:
            first = await asyncio.wait_for(self._q.get(), timeout=window_seconds)
            batch.append(first)
        except asyncio.TimeoutError:
            return batch
        while len(batch) < size:
            try:
                batch.append(self._q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def complete(self, item: QueueItem) -> None:
        self._done.append(item)


__all__ = [
    "TaskType",
    "QueueItem",
    "Observation",
    "ObservationSink",
    "InMemoryObservationSink",
    "LLMCaller",
    "default_llm_caller",
    "minimal_deriver_prompt",
    "DeriverWorker",
    "DeriverQueue",
    "InMemoryDeriverQueue",
]
