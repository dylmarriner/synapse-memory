"""Hierarchical Retrieval — directory-scoped search with score propagation.

Extends the existing search system with directory-aware retrieval:
1. Search within a specific directory tree (synapse://user/{name}/memories/{type})
2. Score propagation from parent directories to children
3. L0/L1/L2 level filtering for tiered context building
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.vfs import MEMORY_TYPE_DIRS

log = logging.getLogger("nexus.retrieval.hierarchical")
router = APIRouter()


@router.post("/search/dir")
async def directory_search(
    query: str = Query(..., description="Search query"),
    directory_uri: str = Query("synapse://", description="Directory URI to search within"),
    limit: int = Query(10, ge=1, le=100),
    level: int | None = Query(None, description="Filter by level: 0=L0, 1=L1, 2=L2"),
    memory_type: str | None = Query(None, description="Filter by memory type (preferences, entities, etc.)"),
    db: AsyncSession = Depends(get_db),
):
    """Search within a directory tree using the URI hierarchy.

    Returns results arranged by directory with scores.
    """
    prefix = _directory_prefix(directory_uri, memory_type)
    if not prefix:
        return {"query": query, "count": 0, "directories": [], "results": []}

    conditions = ["m.uri LIKE :prefix"]
    params: dict = {"prefix": f"{prefix}%", "query": f"%{query}%", "lim": limit}

    if level is not None:
        conditions.append("m.level = :level")
        params["level"] = level

    # Search across content, abstract, and overview
    conditions.append(
        "(m.content ILIKE :q OR m.abstract ILIKE :q2 OR m.overview ILIKE :q3)"
    )
    params.update({"q": f"%{query}%", "q2": f"%{query}%", "q3": f"%{query}%"})

    sql = f"""SELECT m.id, m.uri, m.content, m.abstract, m.overview, m.level,
                     m.memory_type, m.importance, m.access_count, m.created_at
              FROM memories m
              WHERE {' AND '.join(conditions)}
              ORDER BY m.importance DESC, m.access_count DESC
              LIMIT :lim
    """

    rows = await db.execute(text(sql), params)
    results = [dict(r._mapping) for r in rows.fetchall()]

    # Group by directory
    dirs = {}
    for r in results:
        uri = r["uri"]
        parts = uri.split("/")
        if len(parts) >= 7:
            dir_key = "/".join(parts[:7])  # synapse://user/{name}/memories/{type}
        else:
            dir_key = "/".join(parts[:-1])
        if dir_key not in dirs:
            dirs[dir_key] = {"directory": dir_key, "count": 0, "results": []}
        dirs[dir_key]["results"].append(r)
        dirs[dir_key]["count"] += 1

    return {
        "query": query,
        "directory_uri": directory_uri,
        "total": len(results),
        "directories": list(dirs.values()),
        "results": results,
    }


@router.get("/search/levels")
async def level_search(
    agent_id: str = Query("default", description="Agent name"),
    level: int = Query(0, description="Context level to retrieve: 0=L0, 1=L1"),
    memory_type: str | None = Query(None, description="Filter by memory type"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve L0 abstracts or L1 overviews for context building.

    This is the primary method for building tiered agent context:
    - L0: load all abstracts for a quick scan
    - L1: load overviews of relevant sections
    - L2: load full content of selected items
    """
    conditions = ["a.name = :agent", "m.level = :level"]
    params = {"agent": agent_id, "level": level, "lim": limit}

    if memory_type:
        if memory_type in MEMORY_TYPE_DIRS:
            conditions.append("m.uri LIKE :prefix")
            params["prefix"] = f"synapse://user/{agent_id}/memories/{memory_type}/%"
        else:
            conditions.append("m.memory_type = :mtype")
            params["mtype"] = memory_type

    if level == 0:
        select_cols = "m.id, m.uri, m.abstract as content, m.memory_type, m.importance"
    else:
        select_cols = "m.id, m.uri, m.overview as content, m.memory_type, m.importance"

    sql = f"""SELECT {select_cols}
              FROM memories m
              JOIN agents a ON m.agent_id = a.id
              WHERE {' AND '.join(conditions)}
              ORDER BY m.importance DESC, m.created_at DESC
              LIMIT :lim
    """
    rows = await db.execute(text(sql), params)
    results = [dict(r._mapping) for r in rows.fetchall()]
    return {"agent_id": agent_id, "level": level, "count": len(results), "results": results}


@router.get("/search/context")
async def build_context(
    agent_id: str = Query("default", description="Agent name"),
    token_budget: int = Query(2000, ge=100, le=16000),
    focus_types: str | None = Query(None, description="Comma-separated memory types to include"),
    db: AsyncSession = Depends(get_db),
):
    """Build a tiered context pack for an agent.

    Algorithm:
    1. Load L0 abstracts for all memory types (cheap scan)
    2. Load L1 overviews for highest-importance types
    3. Load L2 full content for top entries within budget
    """
    types = focus_types.split(",") if focus_types else sorted(MEMORY_TYPE_DIRS)
    used_tokens = 0
    pack = {"agent_id": agent_id, "levels": {}, "total_entries": 0}

    # L0: all abstracts
    l0_results = []
    for mtype in types:
        rows = await db.execute(
            text("""SELECT m.uri, m.abstract, m.memory_type, m.importance
                     FROM memories m
                     JOIN agents a ON m.agent_id = a.id
                     WHERE a.name = :agent AND m.level = 0
                     AND m.uri LIKE :prefix AND m.abstract IS NOT NULL
                     ORDER BY m.importance DESC
                     LIMIT 10
            """),
            {"agent": agent_id, "prefix": f"synapse://user/{agent_id}/memories/{mtype}/%"},
        )
        for r in rows.fetchall():
            l0_results.append(dict(r._mapping))

    pack["levels"]["L0"] = {"count": len(l0_results), "entries": l0_results}
    used_tokens += sum(len((r.get("abstract") or "")) for r in l0_results)
    pack["total_entries"] += len(l0_results)

    # L1: overviews for types with enough budget
    if used_tokens < token_budget * 0.3:
        l1_results = []
        for mtype in types:
            remaining = token_budget - used_tokens
            if remaining < 200:
                break
            rows = await db.execute(
                text("""SELECT m.uri, m.overview, m.memory_type, m.importance
                         FROM memories m
                         JOIN agents a ON m.agent_id = a.id
                         WHERE a.name = :agent AND m.level = 1
                         AND m.uri LIKE :prefix AND m.overview IS NOT NULL
                         ORDER BY m.importance DESC
                         LIMIT 5
                """),
                {"agent": agent_id, "prefix": f"synapse://user/{agent_id}/memories/{mtype}/%"},
            )
            batch = [dict(r._mapping) for r in rows.fetchall()]
            if batch:
                l1_results.extend(batch)
                used_tokens += sum(len((r.get("overview") or "")) for r in batch)

        pack["levels"]["L1"] = {"count": len(l1_results), "entries": l1_results}
        pack["total_entries"] += len(l1_results)

    # L2: top full content
    if used_tokens < token_budget * 0.7:
        remaining = token_budget - used_tokens
        rows = await db.execute(
            text("""SELECT m.uri, LEFT(m.content, :maxlen) as content, m.memory_type, m.importance
                     FROM memories m
                     JOIN agents a ON m.agent_id = a.id
                     WHERE a.name = :agent AND m.level = 2
                     ORDER BY m.importance DESC
                     LIMIT 5
            """),
            {"agent": agent_id, "maxlen": min(remaining // 5, 2000)},
        )
        l2_results = [dict(r._mapping) for r in rows.fetchall()]
        pack["levels"]["L2"] = {"count": len(l2_results), "entries": l2_results}
        pack["total_entries"] += len(l2_results)

    return pack


# ── Internal ─────────────────────────────────────────────────────────────────

def _directory_prefix(uri: str, memory_type: str | None) -> str | None:
    """Derive the SQL LIKE prefix from a directory URI."""
    if not uri or uri == "synapse://":
        return "synapse://user/"
    if uri.startswith("synapse://user/") and memory_type:
        parts = uri.split("/")
        if len(parts) >= 4:
            user = parts[3]
            return f"synapse://user/{user}/memories/{memory_type}"
    return uri
