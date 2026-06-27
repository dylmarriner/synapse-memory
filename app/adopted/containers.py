"""Container tags — the scope key for everything memory-related.

Every memory in Nexus is tagged with a `container_tag` (also called a
`scope_key` or `workspace`).  Recall, profile, profile-building, and
the auto-forgetting all use this tag to slice the corpus:

- "user:alice"          — everything about the user Alice
- "project:atlas"       — everything about the Atlas project
- "team:platform-eng"   — everything the platform-eng team has learned
- "agent:hermes"        — everything Hermes has observed
- "global"              — the shared pool visible to every agent

A tag is a string with a single colon separating the kind from the name.
The kind is opaque to the storage layer — it's just a label.  Common
kinds: `user`, `project`, `team`, `agent`, `topic`, `global`.

The value of a tag is its string form.  Two tags are equal if their
strings are equal.  Tags are not hierarchical: "user:alice" is not a
sub-tag of "user".  If you want hierarchy, use the wing/room/drawer
scope module.

This module is intentionally tiny: just normalisation, validation, and a
few conveniences.  The actual storage and routing lives elsewhere.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence, Set

# Reserved tag names.  "global" is the unscoped shared pool.
RESERVED_TAGS: frozenset = frozenset({"global", "*"})

# Allowed characters in a tag: a-z, 0-9, dash, underscore, colon, dot.
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


def normalize(tag: str) -> str:
    """Coerce a tag string into canonical form: lowercase, no spaces,
    characters limited to `[a-z0-9._:-]`.

    Returns "" if the input is empty or contains only illegal characters.
    """
    if not tag:
        return ""
    tag = tag.strip().lower()
    tag = re.sub(r"[\s/]+", "", tag)
    tag = re.sub(r"[^a-z0-9._:-]", "", tag)
    # Strip leading/trailing separators from each section.
    return ":".join(_strip_edges(s) for s in tag.split(":") if s or _strip_edges(s))


def _strip_edges(s: str) -> str:
    return s.strip("._:-") or s


def is_valid(tag: str) -> bool:
    """True if `tag` is a well-formed container tag."""
    if not tag or tag in RESERVED_TAGS:
        return tag in RESERVED_TAGS
    return bool(_TAG_RE.match(tag))


def kind_of(tag: str) -> Optional[str]:
    """Return the kind prefix (`user`, `project`, etc.) or None."""
    norm = normalize(tag)
    if not norm or norm in RESERVED_TAGS:
        return None
    if ":" in norm:
        return norm.split(":", 1)[0]
    return None


def name_of(tag: str) -> Optional[str]:
    """Return the name portion of a `kind:name` tag, or None for unscoped tags."""
    norm = normalize(tag)
    if not norm or norm in RESERVED_TAGS:
        return None
    if ":" in norm:
        return norm.split(":", 1)[1]
    return norm


def parse(tag: str) -> tuple:
    """Return `(kind, name)` or `(None, tag)` for an unscoped tag."""
    norm = normalize(tag)
    if not norm or norm in RESERVED_TAGS:
        return (None, norm)
    if ":" in norm:
        kind, name = norm.split(":", 1)
        return (kind, name)
    return (None, norm)


def make(kind: str, name: str) -> str:
    """Build a `kind:name` tag from the two parts."""
    if not kind or not name:
        raise ValueError("both kind and name are required")
    if ":" in kind or ":" in name:
        raise ValueError("kind and name must not contain ':'")
    return normalize(f"{kind}:{name}")


def matches(query: str, candidate: str) -> bool:
    """Return True if `query` is a tag-set match for `candidate`.

    Currently the only wildcard is the reserved "*" which matches
    every tag.  This is intentionally restrictive — exact-match tag
    semantics are what most callers want.
    """
    q = normalize(query)
    c = normalize(candidate)
    if q == "*" or q == c:
        return True
    return False


def filter_(items: Iterable[Any], tag: str, *, attr: str = "container_tag") -> List[Any]:
    """Return only items whose `attr` is `tag` (or matches its wildcard)."""
    return [it for it in items if matches(tag, getattr(it, attr, ""))]


def common_ancestor(*tags: str) -> Optional[str]:
    """Return the longest common prefix tag, or None if there is no overlap.

    The reserved "global" is the universal ancestor: if any tag is
    "global", the common ancestor is the longest non-global prefix of
    the remaining tags.
    """
    norm = [normalize(t) for t in tags if t]
    if not norm:
        return None
    if "global" in norm:
        others = [t for t in norm if t != "global"]
        if not others:
            return "global"
        return _common_prefix(others)
    return _common_prefix(norm)


def _common_prefix(tags: Sequence[str]) -> Optional[str]:
    if not tags:
        return None
    if len(tags) == 1:
        return tags[0]
    parts = [t.split(":") for t in tags]
    common: List[str] = []
    for group in zip(*parts):
        if len(set(group)) == 1:
            common.append(group[0])
        else:
            break
    if not common:
        return None
    return ":".join(common)


__all__ = [
    "RESERVED_TAGS",
    "normalize",
    "is_valid",
    "kind_of",
    "name_of",
    "parse",
    "make",
    "matches",
    "filter_",
    "common_ancestor",
]
