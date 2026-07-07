"""Virtual Filesystem router — ls, tree, mkdir, rm, stat on synapse:// URIs.

Provides a filesystem-style interface to browse and manage the
hierarchical memory namespace.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.vfs import (
    parse_uri, is_directory, parent_uri, normalize_uri, uri_depth,
    MEMORY_TYPE_DIRS, USER_DIRS, URI_SCHEME,
)

log = logging.getLogger("nexus.routers.vfs")
router = APIRouter()


# ── Directory listing ────────────────────────────────────────────────────────

@router.get("/fs/ls")
async def fs_ls(
    uri: str = Query("synapse://", description="Directory URI to list"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List contents of a synapse:// directory (virtual + DB-backed)."""
    uri = normalize_uri(uri)
    parts = parse_uri(uri)

    if not parts["scope"]:
        return _ls_root(db)

    if parts["scope"] == "user":
        return await _ls_user_scope(db, uri, parts, limit, offset)

    if parts["scope"] == "resources":
        return await _ls_resources_scope(db, uri, parts, limit, offset)

    if parts["scope"] == "agent":
        return await _ls_agent_scope(db, uri, parts, limit, offset)

    raise HTTPException(status_code=400, detail=f"Unknown scope: {parts['scope']}")


@router.get("/fs/tree")
async def fs_tree(
    uri: str = Query("synapse://", description="Root URI for tree view"),
    depth: int = Query(3, ge=1, le=6),
    db: AsyncSession = Depends(get_db),
):
    """Return a nested tree structure for browse UI."""
    tree = await _build_tree(db, normalize_uri(uri), depth, 0)
    return {"uri": uri, "tree": tree}


@router.get("/fs/stat")
async def fs_stat(
    uri: str = Query(..., description="URI to stat"),
    db: AsyncSession = Depends(get_db),
):
    """Return metadata about a URI (file or directory)."""
    uri = normalize_uri(uri)
    parts = parse_uri(uri)

    # Check directory_nodes cache first
    row = await db.execute(
        text("SELECT uri, name, entry_type, is_leaf, description, child_count, "
             "created_at, updated_at FROM directory_nodes WHERE uri = :uri"),
        {"uri": uri},
    )
    node = row.fetchone()
    if node:
        return dict(node._mapping)

    # Check if it's a predefined directory
    if is_directory(uri):
        name = uri.rstrip("/").split("/")[-1] or "root"
        child_count = await _count_children(db, uri)
        return {
            "uri": uri,
            "name": name,
            "entry_type": "directory",
            "is_leaf": False,
            "description": _dir_description(uri, parts),
            "child_count": child_count,
        }

    # Check memories table
    row = await db.execute(
        text("SELECT id, uri, content, abstract, memory_type, importance, "
             "created_at FROM memories WHERE uri = :uri LIMIT 1"),
        {"uri": uri},
    )
    mem = row.fetchone()
    if mem:
        return {"uri": uri, "entry_type": "memory", **dict(mem._mapping)}

    raise HTTPException(status_code=404, detail=f"URI not found: {uri}")


# ── Mutations ────────────────────────────────────────────────────────────────

@router.post("/fs/mkdir")
async def fs_mkdir(
    uri: str = Query(..., description="Directory URI to create"),
    description: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a directory node in the virtual filesystem."""
    uri = normalize_uri(uri)
    if not is_directory(uri):
        raise HTTPException(status_code=400, detail=f"URI is not a directory: {uri}")

    parts = parse_uri(uri)
    name = uri.rstrip("/").split("/")[-1]
    parent = parent_uri(uri)
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""INSERT INTO directory_nodes (id, uri, parent_uri, name, entry_type,
                is_leaf, description, child_count, created_at, updated_at)
                VALUES (gen_random_uuid(), :uri, :parent, :name, 'directory',
                        FALSE, :desc, 0, :now, :now)
                ON CONFLICT (uri) DO UPDATE SET description = COALESCE(NULLIF(:desc2, ''), directory_nodes.description)
        """),
        {"uri": uri, "parent": parent, "name": name, "desc": description or "",
         "now": now, "desc2": description or ""},
    )
    await db.commit()

    # Auto-create ancestors if needed
    if parent:
        await _ensure_ancestor(db, parent)

    return {"uri": uri, "name": name, "status": "created"}


@router.delete("/fs/rm")
async def fs_rm(
    uri: str = Query(..., description="URI to remove"),
    recursive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Remove a directory node or memory entry."""
    uri = normalize_uri(uri)

    if is_directory(uri):
        if not recursive:
            child_count = await _count_children(db, uri)
            if child_count > 0:
                raise HTTPException(400, f"Directory not empty ({child_count} children). Use recursive=True.")
        await db.execute(text("DELETE FROM directory_nodes WHERE uri = :uri OR parent_uri = :uri2"),
                         {"uri": uri, "uri2": uri})
        await db.commit()
    else:
        await db.execute(text("DELETE FROM memories WHERE uri = :uri"), {"uri": uri})
        await db.execute(text("DELETE FROM directory_nodes WHERE uri = :uri"), {"uri": uri})
        await db.commit()

    return {"uri": uri, "status": "deleted"}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _ls_root(db):
    """Virtual root: list top-level scopes."""
    entries = [
        {"name": "user", "uri": "synapse://user", "entry_type": "directory",
         "description": "User-scoped data (memories, resources, skills, peers)"},
        {"name": "resources", "uri": "synapse://resources", "entry_type": "directory",
         "description": "Global shared resources"},
        {"name": "agent", "uri": "synapse://agent", "entry_type": "directory",
         "description": "Agent-scoped definitions (skills, tools)"},
    ]
    return {"uri": "synapse://", "count": len(entries), "entries": entries}


async def _ls_user_scope(db, uri: str, parts: dict, limit: int, offset: int):
    """List contents of a synapse://user/{name}/... directory."""
    name = parts["owner"]
    if not parts["category"]:
        # synapse://user/{name} — show top-level user dirs
        entries = []
        for d in sorted(USER_DIRS):
            du = f"synapse://user/{name}/{d}"
            desc = _dir_description(du, parse_uri(du))
            db_count = await _count_children(db, du)
            entries.append({"name": d, "uri": du, "entry_type": "directory",
                            "description": desc, "child_count": db_count})
        return {"uri": uri, "owner": name, "count": len(entries), "entries": entries}

    if parts["category"] == "memories":
        if not parts["subcategory"]:
            # synapse://user/{name}/memories — list memory type dirs
            entries = await _get_or_create_memory_dirs(db, name)
            return {"uri": uri, "owner": name, "count": len(entries), "entries": entries}

        # synapse://user/{name}/memories/{type} — list memory entries
        return await _list_memories_in_dir(db, name, parts["subcategory"], limit, offset)

    if parts["category"] == "peers":
        if not parts["subcategory"]:
            return await _list_peer_dirs(db, name, limit, offset)
        peer_id = parts["subcategory"]
        entries = []
        for d in sorted(PEER_DIRS):
            du = f"synapse://user/{name}/peers/{peer_id}/{d}"
            entries.append({"name": d, "uri": du, "entry_type": "directory",
                            "description": f"Peer {peer_id} {d}"})
        return {"uri": uri, "owner": name, "peer": peer_id, "count": len(entries), "entries": entries}

    # resources, skills, sessions, privacy
    if parts["category"] in ("resources", "skills", "sessions", "privacy"):
        return await _list_generic_dir(db, name, parts["category"], limit, offset)

    return {"uri": uri, "count": 0, "entries": []}


async def _ls_resources_scope(db, uri, parts, limit, offset):
    # synapse://resources — global resources
    rows = await db.execute(
        text("SELECT r.id, r.name, r.uri, r.description FROM directory_nodes r "
             "WHERE r.uri LIKE 'synapse://resources/%' "
             "ORDER BY r.name LIMIT :lim OFFSET :off"),
        {"lim": limit, "off": offset},
    )
    entries = [dict(r._mapping) for r in rows.fetchall()]
    return {"uri": uri, "count": len(entries), "entries": entries}


async def _ls_agent_scope(db, uri, parts, limit, offset):
    # synapse://agent/skills — shared agent skills
    if parts.get("category") == "skills":
        rows = await db.execute(
            text("SELECT id, name, description, tags, version, updated_at "
                 "FROM skills ORDER BY updated_at DESC LIMIT :lim OFFSET :off"),
            {"lim": limit, "off": offset},
        )
        entries = [dict(r._mapping) for r in rows.fetchall()]
        return {"uri": uri, "count": len(entries), "entries": entries}
    # synapse://agent — top level
    return {"uri": uri, "entries": [
        {"name": "skills", "uri": "synapse://agent/skills", "entry_type": "directory",
         "description": "Shared agent skill definitions"}
    ]}


async def _list_memories_in_dir(db, agent_name: str, memory_type: str, limit: int, offset: int):
    """List memory entries in a specific type directory."""
    prefix = f"synapse://user/{agent_name}/memories/{memory_type}/"
    rows = await db.execute(
        text("""SELECT id, uri, content, abstract, memory_type, importance,
                       access_count, created_at
                FROM memories
                WHERE uri LIKE :prefix
                ORDER BY importance DESC, created_at DESC
                LIMIT :lim OFFSET :off
        """),
        {"prefix": f"{prefix}%", "lim": limit, "off": offset},
    )
    entries = []
    for r in rows.fetchall():
        d = dict(r._mapping)
        d["entry_type"] = "memory"
        entries.append(d)

    count = await db.scalar(
        text("SELECT COUNT(*) FROM memories WHERE uri LIKE :prefix"),
        {"prefix": f"{prefix}%"},
    )

    return {"uri": f"synapse://user/{agent_name}/memories/{memory_type}",
            "owner": agent_name, "count": count or 0, "entries": entries}


async def _list_generic_dir(db, agent_name: str, category: str, limit: int, offset: int):
    """List items under a generic category (resources, skills, etc.)."""
    prefix = f"synapse://user/{agent_name}/{category}/"
    rows = await db.execute(
        text("SELECT uri, name, description, child_count, updated_at "
             "FROM directory_nodes WHERE uri LIKE :prefix "
             "ORDER BY name LIMIT :lim OFFSET :off"),
        {"prefix": f"{prefix}%", "lim": limit, "off": offset},
    )
    entries = [dict(r._mapping) for r in rows.fetchall()]
    count = await db.scalar(
        text("SELECT COUNT(*) FROM directory_nodes WHERE uri LIKE :prefix"),
        {"prefix": f"{prefix}%"},
    )
    return {"uri": f"synapse://user/{agent_name}/{category}",
            "owner": agent_name, "count": count or 0, "entries": entries}


async def _list_peer_dirs(db, agent_name: str, limit: int, offset: int):
    """List peer directories."""
    prefix = f"synapse://user/{agent_name}/peers/"
    rows = await db.execute(
        text("SELECT uri, name, description, child_count, updated_at "
             "FROM directory_nodes WHERE uri LIKE :prefix AND entry_type = 'directory' "
             "ORDER BY name LIMIT :lim OFFSET :off"),
        {"prefix": f"{prefix}%", "lim": limit, "off": offset},
    )
    entries = [dict(r._mapping) for r in rows.fetchall()]
    count = await db.scalar(
        text("SELECT COUNT(*) FROM directory_nodes WHERE uri LIKE :prefix AND entry_type = 'directory'"),
        {"prefix": f"{prefix}%"},
    )
    return {"uri": f"synapse://user/{agent_name}/peers",
            "owner": agent_name, "count": count or 0, "entries": entries}


async def _get_or_create_memory_dirs(db, agent_name: str):
    """Return memory type directories, ensuring they exist in DB."""
    base = f"synapse://user/{agent_name}/memories"
    prefix = f"{base}/"
    now = datetime.now(timezone.utc)

    entries = []
    for dtype in sorted(MEMORY_TYPE_DIRS):
        du = f"{prefix}{dtype}"
        desc = _memory_type_desc(dtype)
        child_count = await db.scalar(
            text("SELECT COUNT(*) FROM memories WHERE uri LIKE :prefix"),
            {"prefix": f"{du}%"},
        )
        entries.append({
            "name": dtype, "uri": du, "entry_type": "directory",
            "description": desc, "child_count": child_count or 0,
        })
        # Ensure directory node exists
        await db.execute(
            text("""INSERT INTO directory_nodes (id, uri, parent_uri, name, entry_type,
                    is_leaf, description, child_count, created_at, updated_at)
                    VALUES (gen_random_uuid(), :uri, :parent, :name, 'directory',
                            FALSE, :desc, :cc, :now, :now)
                    ON CONFLICT (uri) DO UPDATE SET child_count = :cc2, updated_at = :now2
            """),
            {"uri": du, "parent": base, "name": dtype, "desc": desc,
             "cc": child_count or 0, "now": now,
             "cc2": child_count or 0, "now2": now},
        )
    await db.commit()
    return entries


async def _ensure_ancestor(db, uri: str):
    """Create parent directory nodes up to the root."""
    if uri in ("synapse://", "synapse://user"):
        return
    parts = parse_uri(uri)
    if not parts["scope"]:
        return
    name = uri.rstrip("/").split("/")[-1]
    parent = parent_uri(uri)
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""INSERT INTO directory_nodes (id, uri, parent_uri, name, entry_type,
                is_leaf, child_count, created_at, updated_at)
                VALUES (gen_random_uuid(), :uri, :parent, :name, 'directory',
                        FALSE, 0, :now, :now)
                ON CONFLICT (uri) DO NOTHING
        """),
        {"uri": uri, "parent": parent, "name": name, "now": now},
    )
    await db.commit()
    if parent:
        await _ensure_ancestor(db, parent)


async def _count_children(db, uri: str) -> int:
    """Count immediate children of a URI."""
    count = await db.scalar(
        text("SELECT COUNT(*) FROM directory_nodes WHERE parent_uri = :uri"),
        {"uri": uri},
    )
    if count is None or count == 0:
        # Check memories
        count = await db.scalar(
            text("SELECT COUNT(*) FROM memories WHERE parent_uri = :uri"),
            {"uri": uri},
        )
    return count or 0


async def _build_tree(db, uri: str, max_depth: int, current_depth: int):
    """Recursively build a tree structure."""
    if current_depth >= max_depth:
        return {"uri": uri, "name": uri.split("/")[-1], "truncated": True}

    # Get children from directory_nodes + memories
    rows = await db.execute(
        text("SELECT uri, name, entry_type, is_leaf, child_count, description "
             "FROM directory_nodes WHERE parent_uri = :uri "
             "ORDER BY entry_type DESC, name LIMIT 50"),
        {"uri": uri},
    )
    children = []
    for r in rows.fetchall():
        node = dict(r._mapping)
        if node["entry_type"] == "directory" and not node["is_leaf"]:
            node["children"] = [await _build_tree(db, node["uri"], max_depth, current_depth + 1)]
        children.append(node)

    # Also fetch memory entries
    mem_rows = await db.execute(
        text("SELECT uri, content, memory_type, importance FROM memories "
             "WHERE parent_uri = :uri ORDER BY importance DESC LIMIT 20"),
        {"uri": uri},
    )
    for r in mem_rows.fetchall():
        children.append({
            "uri": r.uri, "name": r.uri.split("/")[-1],
            "entry_type": "memory", "memory_type": r.memory_type,
        })

    name = uri.split("/")[-1] or "root"
    return {"uri": uri, "name": name, "children": children}


def _dir_description(uri: str, parts: dict) -> str:
    """Provide human-readable description for known directories."""
    if parts["scope"] == "user":
        if not parts["category"]:
            return "User workspace root"
        if parts["category"] == "memories":
            if not parts["subcategory"]:
                return "Long-term memory organized by type"
            return _memory_type_desc(parts["subcategory"])
        if parts["category"] == "resources":
            return "User-owned knowledge resources"
        if parts["category"] == "skills":
            return "Callable skill definitions"
        if parts["category"] == "peers":
            if not parts["subcategory"]:
                return "Memories about interaction peers"
            return f"Peer: {parts['subcategory']}"
        if parts["category"] == "sessions":
            return "Conversation session records"
        if parts["category"] == "privacy":
            return "Sensitive configuration snapshots"
    if parts["scope"] == "resources":
        return "Global shared knowledge resources"
    if parts["scope"] == "agent":
        return "Agent-scoped definitions"
    return ""


def _memory_type_desc(mtype: str) -> str:
    descs = {
        "preferences": "User preferences by topic",
        "entities": "People, projects, and concepts",
        "events": "Important occurrences",
        "patterns": "Reusable methods and workflows",
        "cases": "Specific problems and resolutions",
        "tools": "Tool usage experience",
        "skills": "Skill execution experience",
        "trajectories": "End-to-end task traces",
        "experiences": "Generalized from trajectories",
    }
    return descs.get(mtype, f"{mtype} memories")
