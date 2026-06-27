"""Time-bounded memories via an `expiration_date` (ISO `YYYY-MM-DD`) in the
metadata.  No decay job, no scheduled cleanup — just a filter at search
time.  This is the simplest possible auto-forgetting primitive.

Exposes three pure functions:

- `is_expired()` — is this memory past its expiration?
- `filter_expired()` — drop expired memories from a result list.
- `make_expirable()` — produce the metadata dict that opts a memory in.

The expiration date is stored under the metadata key `expiration_date`.
To make a memory ephemeral, pass `metadata=make_expirable("2026-12-31")`
to `save_memory`.  After that date the memory hides from search and
recall, but is not deleted — `show_expired=True` reveals it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

EXPIRATION_KEY = "expiration_date"


def _coerce(value: Any) -> date:
    """Coerce a date / datetime / ISO string into a `date`.  Raise on garbage."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(
        f"expiration_date must be a date, datetime, or ISO string — got {type(value).__name__}"
    )


def is_expired(payload: Mapping[str, Any], *, now: date | None = None) -> bool:
    """Return True if this memory's `expiration_date` is in the past."""
    raw = payload.get(EXPIRATION_KEY)
    if not raw:
        return False
    try:
        exp = _coerce(raw)
    except ValueError:
        # Garbage in metadata — treat as not-expired, log upstream.
        return False
    today = now or datetime.now(timezone.utc).date()
    return exp < today


def filter_expired(
    memories: Iterable[Mapping[str, Any]],
    *,
    now: date | None = None,
) -> List[Mapping[str, Any]]:
    """Return only memories that are NOT past their expiration date."""
    return [m for m in memories if not is_expired(m, now=now)]


def make_expirable(expiration: date | datetime | str) -> Dict[str, str]:
    """Return the metadata dict that opts a memory in to auto-expiration.

    Usage:
        save_memory(..., metadata=make_expirable("2026-12-31"))
    """
    return {EXPIRATION_KEY: _coerce(expiration).isoformat()}


__all__ = [
    "EXPIRATION_KEY",
    "is_expired",
    "filter_expired",
    "make_expirable",
]
