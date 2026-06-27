"""Hierarchical scope: wing > room > drawer.

A scope is a path-like string with up to three dot-separated segments:

    wing                    e.g. "auth"
    wing.room              e.g. "auth.jwt"
    wing.room.drawer       e.g. "auth.jwt.refresh"

Searches can be scoped to a wing, a room, or a drawer; the scope filter
narrows results to that sub-tree.

Wings and rooms are organizational labels — they exist to make search
results more focused and to let the user say "look in `auth.jwt` only".
Drawers are the actual memory items; a memory lives in exactly one drawer
(or, if no drawer is set, in the wing's root drawer).

Scope strings are normalized to lowercase, with internal whitespace and
slashes converted to dots.  A trailing dot is stripped.

The use of three levels (rather than N levels) keeps the mental model
small and matches the way humans actually describe work
("the JWT refresh bug in auth") without the unbounded depth of a tag
hierarchy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

_DOT_RE = re.compile(r"\s+|/+")
_INVALID_RE = re.compile(r"[^a-z0-9._-]")


def normalize(scope: str) -> str:
    """Coerce a free-form scope string into `wing.room.drawer` form.

    - Whitespace and slashes become dots
    - All characters are lowercased
    - Allowed characters: a-z, 0-9, dot, underscore, dash
    - Other characters are stripped
    - Leading and trailing dots are removed
    - Empty parts are collapsed
    """
    if not scope:
        return ""
    scope = scope.strip().lower()
    scope = _DOT_RE.sub(".", scope)
    scope = _INVALID_RE.sub("", scope)
    parts = [p for p in scope.split(".") if p]
    return ".".join(parts)


def split(scope: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split a normalized scope into (wing, room, drawer).

    Returns ("auth", "jwt", "refresh") for "auth.jwt.refresh".
    Returns ("auth", "jwt", None) for "auth.jwt".
    Returns ("auth", None, None) for "auth".
    Returns ("", None, None) for "".
    """
    norm = normalize(scope)
    if not norm:
        return "", None, None
    parts = norm.split(".")
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], parts[1], parts[2]


def join(wing: str, room: Optional[str] = None, drawer: Optional[str] = None) -> str:
    """Inverse of `split` — build a scope string from parts."""
    parts = [normalize(wing)]
    if room:
        parts.append(normalize(room))
    if drawer:
        parts.append(normalize(drawer))
    return ".".join(p for p in parts if p)


def parent(scope: str) -> Optional[str]:
    """Return the parent scope, or None if already at the top level."""
    wing, room, drawer = split(scope)
    if drawer is not None:
        return join(wing, room)
    if room is not None:
        return join(wing)
    if wing:
        return ""
    return None


def depth(scope: str) -> int:
    """Return the depth of a scope: 0 for root, 1 for wing, etc."""
    wing, room, drawer = split(scope)
    return (1 if wing else 0) + (1 if room else 0) + (1 if drawer else 0)


def matches(query: str, candidate: str) -> bool:
    """Return True if `query` is an ancestor of `candidate` or equal to it.

    `matches("auth", "auth.jwt")` -> True
    `matches("auth.jwt", "auth")` -> False
    `matches("auth.jwt", "auth.jwt")` -> True
    `matches("", "auth.jwt")` -> True (empty scope matches everything)
    """
    q = normalize(query)
    c = normalize(candidate)
    if not q:
        return True
    if q == c:
        return True
    return c.startswith(q + ".")


def filter_(items: Iterable[Tuple[str, object]], scope: str) -> List[Tuple[str, object]]:
    """Return only items whose scope is contained within `scope`."""
    return [(s, v) for s, v in items if matches(scope, s)]


@dataclass(frozen=True)
class ScopeFilter:
    """A reusable scope predicate.

    Use as `ScopeFilter("auth.jwt")(memory.scope)`.  Pre-compile when the
    same scope is matched many times.
    """
    scope: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", normalize(self.scope))

    def __call__(self, candidate: str) -> bool:
        return matches(self.scope, candidate)


__all__ = [
    "normalize",
    "split",
    "join",
    "parent",
    "depth",
    "matches",
    "filter_",
    "ScopeFilter",
]
