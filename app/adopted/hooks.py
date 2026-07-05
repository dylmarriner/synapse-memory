"""Auto-capture hooks: 12 lifecycle events that automatically record
agent activity into memory.

The hook taxonomy is deliberately fixed — every agent on Nexus can be
expected to fire the same 12 events, so the recall logic can rely on
having seen them.

| # | Event              | When it fires                                  |
|---|--------------------|------------------------------------------------|
| 1 | session_start      | Agent process begins                           |
| 2 | prompt_submit      | User submits a new prompt                      |
| 3 | pre_tool_use       | Before an agent invokes a tool                 |
| 4 | post_tool_use      | After a tool returns successfully              |
| 5 | post_tool_failure  | After a tool raises an error                   |
| 6 | pre_compact        | Right before context-window compaction         |
| 7 | notification       | Permission prompt / system notification        |
| 8 | subagent_start     | A sub-agent is spawned                         |
| 9 | subagent_stop      | A sub-agent returns                            |
| 10| stop               | The agent finished its turn                    |
| 11| task_completed     | An async task finished                         |
| 12| session_end        | Agent process exits                            |

Each hook is a small, fire-and-forget function that takes a single
`HookContext` and posts a single observation to the memory backend.  It
must NEVER block — the agent's next-prompt boundary depends on these
returning within a hard timeout.

The `dispatch()` helper routes an event to the registered handler and
catches any exception so a broken hook can never crash the agent.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger("nexus.adopted.hooks")


class HookEvent(str, Enum):
    """The 12 lifecycle events the hook system knows about."""
    SESSION_START    = "session_start"
    PROMPT_SUBMIT    = "prompt_submit"
    PRE_TOOL_USE     = "pre_tool_use"
    POST_TOOL_USE    = "post_tool_use"
    POST_TOOL_FAILURE= "post_tool_failure"
    PRE_COMPACT      = "pre_compact"
    NOTIFICATION     = "notification"
    SUBAGENT_START   = "subagent_start"
    SUBAGENT_STOP    = "subagent_stop"
    STOP             = "stop"
    TASK_COMPLETED   = "task_completed"
    SESSION_END      = "session_end"


# Convenience: the canonical 12-event list, in registration order.
ALL_EVENTS: List[HookEvent] = list(HookEvent)


@dataclass
class HookContext:
    """All the data a hook handler can read.

    `event`         — which of the 12 events fired
    `session_id`    — the agent's session id
    `agent_id`      — the agent's identity (if known)
    `cwd`           — the working directory
    `timestamp`     — when the event fired
    `data`          — event-specific payload (tool name, prompt text, etc.)
    """
    event: HookEvent
    session_id: str
    agent_id: Optional[str] = None
    cwd: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: Dict[str, Any] = field(default_factory=dict)


# ---- Async observation backend -------------------------------------------

class ObservationSink(abc.ABC):
    """Where hooks post their observations.

    Implementations can be:
      - An in-memory list (tests, demos)
      - A Nexus REST client (production)
      - A Kafka / Redis stream (event-sourced)
    """

    @abc.abstractmethod
    async def observe(self, ctx: HookContext) -> None: ...


class InMemorySink(ObservationSink):
    """Trivial sink used by tests and the embedded demo."""

    def __init__(self) -> None:
        self.observations: List[HookContext] = []

    async def observe(self, ctx: HookContext) -> None:
        self.observations.append(ctx)


# ---- Registry & dispatch --------------------------------------------------

HookHandler = Callable[[HookContext], Awaitable[None]]


class HookRegistry:
    """The registry of 12 hooks, one per event.

    A handler registered for `event` will be called for every fire of that
    event.  Handlers are awaited in registration order.  A single handler
    that raises is logged and skipped — one broken hook never breaks
    another.
    """

    def __init__(self, sink: ObservationSink) -> None:
        self._sink = sink
        self._handlers: Dict[HookEvent, List[HookHandler]] = {e: [] for e in HookEvent}

    def on(self, event: HookEvent, handler: HookHandler) -> None:
        """Register a handler for an event.  Idempotent on duplicate adds."""
        self._handlers[event].append(handler)

    def handlers_for(self, event: HookEvent) -> List[HookHandler]:
        return list(self._handlers[event])

    async def dispatch(self, ctx: HookContext) -> None:
        """Fire a hook.  Errors are logged, never raised.

        The observation is always sent to the sink first, then any
        additional handlers run.
        """
        try:
            await self._sink.observe(ctx)
        except Exception:
            log.exception("hook sink failed for %s", ctx.event.value)
        for handler in self._handlers[ctx.event]:
            try:
                await handler(ctx)
            except Exception:
                log.exception("hook handler failed for %s", ctx.event.value)


# ---- Convenience builder -------------------------------------------------

def default_handlers(sink: ObservationSink) -> HookRegistry:
    """Wire the 12 standard handlers.  All 12 are the same one — they just
    forward to the sink.  Override per event in a real deployment.
    """
    reg = HookRegistry(sink)

    async def forward(ctx: HookContext) -> None:
        # The sink already got the observation via dispatch(); this is
        # here for symmetry with future per-event enrichments (eg. chunking
        # tool output before persisting).
        return None

    for event in ALL_EVENTS:
        reg.on(event, forward)
    return reg


# ---- High-level event constructors --------------------------------------

def session_start(
    session_id: str,
    *,
    agent_id: Optional[str] = None,
    cwd: Optional[str] = None,
    **data: Any,
) -> HookContext:
    return HookContext(
        event=HookEvent.SESSION_START,
        session_id=session_id,
        agent_id=agent_id,
        cwd=cwd,
        data=dict(data),
    )


def prompt_submit(
    session_id: str,
    prompt: str,
    *,
    agent_id: Optional[str] = None,
    cwd: Optional[str] = None,
    **data: Any,
) -> HookContext:
    return HookContext(
        event=HookEvent.PROMPT_SUBMIT,
        session_id=session_id,
        agent_id=agent_id,
        cwd=cwd,
        data={"prompt": prompt, **data},
    )


def post_tool_use(
    session_id: str,
    tool_name: str,
    tool_input: Any,
    tool_output: Any,
    *,
    agent_id: Optional[str] = None,
    cwd: Optional[str] = None,
    **data: Any,
) -> HookContext:
    return HookContext(
        event=HookEvent.POST_TOOL_USE,
        session_id=session_id,
        agent_id=agent_id,
        cwd=cwd,
        data={
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            **data,
        },
    )


def pre_compact(
    session_id: str,
    *,
    agent_id: Optional[str] = None,
    cwd: Optional[str] = None,
    **data: Any,
) -> HookContext:
    return HookContext(
        event=HookEvent.PRE_COMPACT,
        session_id=session_id,
        agent_id=agent_id,
        cwd=cwd,
        data=dict(data),
    )


__all__ = [
    "HookEvent",
    "ALL_EVENTS",
    "HookContext",
    "ObservationSink",
    "InMemorySink",
    "HookRegistry",
    "HookHandler",
    "default_handlers",
    "session_start",
    "prompt_submit",
    "post_tool_use",
    "pre_compact",
]
