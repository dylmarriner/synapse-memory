"""Hebbian potentiation + Ebbinghaus exponential decay + Cepeda spacing effect.

A single memory's "strength" drifts toward a floor if it is never accessed,
and grows toward 1.0 every time it is.  Spaced access (>= SPACED_INTERVAL_HOURS
between touches) grows the stability constant, which slows future decay.

All functions are pure: they take a `ConnectionState` and return a new
`ConnectionState`.  The math is:
    new_strength = old_strength * exp(-days_since_last / stability)
    if spaced access:  stability += STABILITY_INCREMENT
    floor at STRENGTH_FLOOR (memory never fully vanishes)

The `score()` function applies the decay to "now" and returns a 0..1
multiplier suitable for re-ranking search results — frequently-accessed
memories float up, untouched memories drift toward the floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Optional

# ---- Tunables — mirror the values in mempalace but with sane Nexus defaults.

# Potentiation — the increment on every co-access.
POTENTIATION_INCREMENT: float = 0.10
MAX_STRENGTH: float = 1.0
STRENGTH_FLOOR: float = 0.05  # never let a memory go fully to zero

# Stability — the half-life-ish denominator of the decay.  Higher = slower decay.
DEFAULT_STABILITY: float = 30.0
STABILITY_INCREMENT: float = 0.50

# Spacing — Cepeda effect: only spaced practice builds durability.
SPACED_INTERVAL_HOURS: float = 12.0


@dataclass(frozen=True)
class ConnectionState:
    """The Ebbinghaus+Hebbian state of a single memory at one point in time.

    `strength` ∈ [STRENGTH_FLOOR, MAX_STRENGTH] — used as a relevance multiplier.
    `stability` — the time constant in the decay exponent (bigger = slower decay).
    `last_activated` — most recent access, anchors the decay clock.
    `access_count` — how many times this connection has been touched.
    """
    strength: float = 0.5
    stability: float = DEFAULT_STABILITY
    last_activated: Optional[datetime] = None
    access_count: int = 0
    created_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Clamp into legal range.
        if self.strength < STRENGTH_FLOOR:
            object.__setattr__(self, "strength", STRENGTH_FLOOR)
        if self.strength > MAX_STRENGTH:
            object.__setattr__(self, "strength", MAX_STRENGTH)


def _hours_since(dt: Optional[datetime], *, now: datetime) -> float:
    if dt is None:
        return 0.0
    delta = (now - dt).total_seconds() / 3600.0
    return max(0.0, delta)


def _days_since(dt: Optional[datetime], *, now: datetime) -> float:
    if dt is None:
        return 0.0
    delta = (now - dt).total_seconds() / 86400.0
    return max(0.0, delta)


def potentiate(
    state: ConnectionState,
    *,
    increment: float = POTENTIATION_INCREMENT,
    now: Optional[datetime] = None,
) -> ConnectionState:
    """Strengthen on access. Spaced practice grows stability.

    Returns a new frozen `ConnectionState` — pure function, no mutation.
    """
    now = now or datetime.now(timezone.utc)
    last = state.last_activated or state.created_at
    hours_since = _hours_since(last, now=now)
    new_strength = min(MAX_STRENGTH, state.strength + increment)
    new_stability = state.stability
    if hours_since >= SPACED_INTERVAL_HOURS:
        new_stability = state.stability + STABILITY_INCREMENT
    return replace(
        state,
        strength=new_strength,
        stability=new_stability,
        last_activated=now,
        access_count=state.access_count + 1,
    )


def apply_decay(
    state: ConnectionState,
    *,
    now: Optional[datetime] = None,
) -> ConnectionState:
    """Ebbinghaus: new = old * exp(-days_since_last / stability), floored."""
    now = now or datetime.now(timezone.utc)
    last = state.last_activated or state.created_at
    if last is None:
        return state
    days = _days_since(last, now=now)
    if days <= 0:
        return state  # idempotent at the same instant
    stability = max(state.stability, DEFAULT_STABILITY)
    decay_factor = math.exp(-days / stability)
    new_strength = max(STRENGTH_FLOOR, state.strength * decay_factor)
    return replace(state, strength=new_strength)


def score(
    state: ConnectionState,
    *,
    now: Optional[datetime] = None,
) -> float:
    """Compute the current relevance multiplier for this connection.

    Returns a value in [STRENGTH_FLOOR, 1.0]. Apply after search to
    re-rank results — frequently-accessed memories float up, untouched
    memories drift toward the floor.
    """
    now = now or datetime.now(timezone.utc)
    decayed = apply_decay(state, now=now)
    return decayed.strength


def fresh() -> ConnectionState:
    """A new connection state anchored to "now"."""
    now = datetime.now(timezone.utc)
    return ConnectionState(
        strength=0.5,
        stability=DEFAULT_STABILITY,
        last_activated=now,
        access_count=0,
        created_at=now,
    )


__all__ = [
    "ConnectionState",
    "POTENTIATION_INCREMENT",
    "MAX_STRENGTH",
    "STRENGTH_FLOOR",
    "DEFAULT_STABILITY",
    "STABILITY_INCREMENT",
    "SPACED_INTERVAL_HOURS",
    "potentiate",
    "apply_decay",
    "score",
    "fresh",
]
