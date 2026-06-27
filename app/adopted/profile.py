"""User profile: a one-call view of what the agent knows about a user.

A profile has two parts:

- **static**  — long-lived facts about the user (role, preferences,
  stable relationships, persistent projects).  These rarely change but
  when they do, the old fact is *superseded*, not deleted.
- **dynamic** — recent activity and short-lived context (the project
  they're working on today, the bug they hit this morning).  These
  auto-decay: a fact about "the auth migration" stops being dynamic
  once the migration is over.

The shape returned by `build_profile()` is:

    {
        "static":  ["User is a senior engineer at Acme", ...],
        "dynamic": ["Working on auth migration", ...],
        "search_results": [...],   # hybrid RAG+Memory hits
    }

The function is pure — it takes a memory list and returns a profile dict.
The caller is responsible for the search step; we provide a
`build_profile_from_recall()` helper that takes the raw recall output and
runs the static/dynamic classifier.

The classifier is a small heuristic + LLM-prompt-ready surface.  For now
the heuristic works on:
  - `expires_at` metadata (dynamic if set, static otherwise)
  - age (memories from the last 14 days default to dynamic, older to static)
  - explicit `profile_class: static | dynamic` metadata (caller-controlled)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional


PROFILE_CLASS_KEY = "profile_class"          # "static" | "dynamic"
PROFILE_STATIC: str = "static"
PROFILE_DYNAMIC: str = "dynamic"

# How many days back counts as "recent" for the auto-classification heuristic.
DEFAULT_DYNAMIC_WINDOW_DAYS: int = 14


@dataclass
class ProfileFact:
    """One fact in the profile, with a stable id and content."""
    id: str
    content: str
    age_days: float
    confidence: float = 1.0
    source: Optional[str] = None
    explicit_class: Optional[str] = None     # one of "static", "dynamic", or None

    @property
    def is_static(self) -> bool:
        return classify(self) == PROFILE_STATIC

    @property
    def is_dynamic(self) -> bool:
        return classify(self) == PROFILE_DYNAMIC


def classify(fact: ProfileFact) -> str:
    """Decide whether a fact is static or dynamic.

    Resolution order:
      1. explicit `profile_class` metadata if set
      2. age > DYNAMIC_WINDOW_DAYS -> static
      3. else -> dynamic
    """
    if fact.explicit_class in (PROFILE_STATIC, PROFILE_DYNAMIC):
        return fact.explicit_class
    if fact.age_days > DEFAULT_DYNAMIC_WINDOW_DAYS:
        return PROFILE_STATIC
    return PROFILE_DYNAMIC


@dataclass
class Profile:
    """The full user profile bundle."""
    static: List[ProfileFact] = field(default_factory=list)
    dynamic: List[ProfileFact] = field(default_factory=list)
    search_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "static": [f.content for f in self.static],
            "dynamic": [f.content for f in self.dynamic],
            "search_results": list(self.search_results),
        }


def build_profile_from_recall(
    hits: Iterable[Mapping[str, Any]],
    *,
    search_results: Optional[Iterable[Mapping[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Profile:
    """Convert a list of recall hits into a static/dynamic Profile."""
    now = now or datetime.now(timezone.utc)
    profile = Profile()
    for h in hits:
        content = h.get("content") or h.get("memory") or ""
        if not content:
            continue
        metadata = h.get("metadata") or {}
        created_at = _parse_dt(metadata.get("created_at"))
        age_days = (now - created_at).total_seconds() / 86400.0 if created_at else 0.0
        fact = ProfileFact(
            id=str(h.get("id", "")),
            content=content,
            age_days=max(0.0, age_days),
            confidence=float(h.get("score", 1.0) or 1.0),
            source=h.get("source"),
            explicit_class=metadata.get(PROFILE_CLASS_KEY),
        )
        if fact.is_static:
            profile.static.append(fact)
        else:
            profile.dynamic.append(fact)
    if search_results is not None:
        profile.search_results = list(search_results)
    return profile


def build_profile_prompt(profile: Profile) -> str:
    """Render a Profile into a system-prompt block the agent can read.

    Output looks like:

        <user_profile>
        <static>
        - User is a senior engineer at Acme
        - User prefers dark mode
        </static>
        <dynamic>
        - Working on the auth migration
        </dynamic>
        </user_profile>
    """
    lines: List[str] = ["<user_profile>"]
    if profile.static:
        lines.append("<static>")
        for f in profile.static:
            lines.append(f"- {f.content}")
        lines.append("</static>")
    if profile.dynamic:
        lines.append("<dynamic>")
        for f in profile.dynamic:
            lines.append(f"- {f.content}")
        lines.append("</dynamic>")
    if not profile.static and not profile.dynamic:
        lines.append("<empty/>")
    lines.append("</user_profile>")
    return "\n".join(lines)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


__all__ = [
    "ProfileFact",
    "Profile",
    "PROFILE_CLASS_KEY",
    "PROFILE_STATIC",
    "PROFILE_DYNAMIC",
    "DEFAULT_DYNAMIC_WINDOW_DAYS",
    "classify",
    "build_profile_from_recall",
    "build_profile_prompt",
]
