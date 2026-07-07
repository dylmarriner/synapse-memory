"""Virtual Filesystem — URI hierarchy for Synapse Memory.

Organizes memories, resources, skills, and peers into a discoverable
filesystem tree using synapse:// URIs.

Directory tree (per user):

  synapse://user/{name}/
    memories/
      preferences/      — user preferences by topic
      entities/         — people, projects, concepts
      events/           — important occurrences
      patterns/         — reusable methods, workflows
      cases/            — specific problem+resolution
      tools/            — tool usage experience
      skills/           — skill execution experience
      trajectories/     — end-to-end task traces
      experiences/      — distilled from trajectories
    resources/          — documents, knowledge
    skills/             — callable skill definitions
    peers/{peer}/       — memories about interaction peers
      memories/
      resources/
    sessions/           — conversation records
    privacy/            — sensitive config snapshots

  synapse://resources/   — global shared resources
  synapse://agent/skills/ — shared agent skills
"""

import re
from typing import Optional

URI_SCHEME = "synapse://"
URI_PATTERN = re.compile(
    r"^synapse://(?P<scope>[^/]+)"
    r"(/(?P<owner>[^/]+))?"
    r"(/(?P<category>[^/]+))?"
    r"(/(?P<subcategory>[^/]+))?"
    r"(/(?P<entry>[^/]+))?"
    r"(?P<extra>(/.*)*)?$"
)

# Standard memory type directories
MEMORY_TYPE_DIRS = frozenset({
    "preferences", "entities", "events", "patterns",
    "cases", "tools", "skills", "trajectories", "experiences",
})

# Top-level user directories
USER_DIRS = frozenset({"memories", "resources", "skills", "peers", "sessions", "privacy"})

# Peer sub-directories
PEER_DIRS = frozenset({"memories", "resources"})


def parse_uri(uri: str) -> dict:
    """Parse a synapse:// URI into components."""
    m = URI_PATTERN.match(uri)
    if not m:
        return {"scope": None, "owner": None, "category": None,
                "subcategory": None, "entry": None}
    return {
        "scope": m.group("scope"),
        "owner": m.group("owner"),
        "category": m.group("category"),
        "subcategory": m.group("subcategory"),
        "entry": m.group("entry"),
    }


def is_directory(uri: str) -> bool:
    """Return True if this URI looks like a directory (no leaf entry)."""
    parts = parse_uri(uri)
    if not parts["scope"]:
        return True  # synapse:// is root
    if parts["scope"] == "user":
        if not parts["owner"]:
            return False  # synapse://user is template, not a real path
        if not parts["category"]:
            return True   # synapse://user/{name}
        if parts["category"] == "memories":
            if not parts["subcategory"]:
                return True  # synapse://user/{name}/memories
            if parts["subcategory"] not in MEMORY_TYPE_DIRS:
                return True  # unknown subcategory = dir
            return not parts["entry"]  # no entry = dir
        if parts["category"] in ("resources", "skills", "privacy", "sessions"):
            return not parts["subcategory"] if parts["category"] in ("skills", "privacy", "sessions") else True
        if parts["category"] == "peers":
            if not parts["subcategory"]:
                return True  # synapse://user/{name}/peers
            if parts["subcategory"] and not parts.get("entry"):
                return True  # peer root
            return False  # peer content dirs
    return True


def parent_uri(uri: str) -> Optional[str]:
    """Return the parent directory URI, or None if root."""
    if uri in ("synapse://", "synapse://user", "synapse://resources", "synapse://agent"):
        return None
    parts = parse_uri(uri)
    if parts["scope"] == "user":
        if not parts["category"]:
            return "synapse://user"
        if parts["category"] == "memories":
            if not parts["subcategory"]:
                return f"synapse://user/{parts['owner']}"
            if not parts["entry"]:
                return f"synapse://user/{parts['owner']}/memories"
            return f"synapse://user/{parts['owner']}/memories/{parts['subcategory']}"
        if parts["category"] == "peers":
            if not parts["subcategory"]:
                return f"synapse://user/{parts['owner']}"
            return f"synapse://user/{parts['owner']}/peers"
        if parts["entry"]:
            return f"synapse://user/{parts['owner']}/{parts['category']}"
        return f"synapse://user/{parts['owner']}"
    return None


def uri_for_memory(agent_name: str, memory_type: str, title: str) -> str:
    """Build a synapse:// URI from agent, type, and title."""
    type_dir = memory_type.rstrip("s") + "s"  # normalize to plural
    if type_dir not in MEMORY_TYPE_DIRS:
        type_dir = memory_type if memory_type in MEMORY_TYPE_DIRS else "other"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    return f"synapse://user/{agent_name}/memories/{type_dir}/{slug}"


def uri_for_skill(agent_name: str, skill_name: str) -> str:
    """Build a URI for a skill definition."""
    slug = re.sub(r"[^a-z0-9]+", "-", skill_name.lower()).strip("-")[:60]
    return f"synapse://user/{agent_name}/skills/{slug}"


def uri_for_resource(agent_name: str, resource_path: str) -> str:
    """Build a URI for a resource."""
    clean = re.sub(r"[^a-z0-9/._-]+", "-", resource_path.lower()).strip("-")
    return f"synapse://user/{agent_name}/resources/{clean}"


def uri_for_peer(agent_name: str, peer_id: str, category: str = "memories") -> str:
    """Build a URI for peer content."""
    return f"synapse://user/{agent_name}/peers/{peer_id}/{category}"


def normalize_uri(uri: str) -> str:
    """Normalize a URI: remove trailing slash, collapse double slashes."""
    return re.sub(r"/+", "/", uri.rstrip("/"))


def uri_depth(uri: str) -> int:
    """Return number of path segments in the URI."""
    parts = uri.replace(URI_SCHEME, "", 1).strip("/").split("/")
    return len(parts) if parts != [""] else 0


def is_memory_uri(uri: str) -> bool:
    """Check if a URI points to a memory entry (leaf under memories/)."""
    parts = parse_uri(uri)
    return (parts["scope"] == "user"
            and parts["category"] == "memories"
            and parts["subcategory"] in MEMORY_TYPE_DIRS
            and parts["entry"] is not None)


def default_memory_dirs() -> list[str]:
    """Return the standard memory subdirectories for discovery."""
    return [d for d in MEMORY_TYPE_DIRS]
