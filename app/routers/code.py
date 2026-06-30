"""Code-context API — code indexing, symbol search, Iris Gate Ladder,
blast radius, wiki generation.  Mirrors what sdl-mcp / jcodemunch /
codesight offer, but lives natively inside Nexus."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.code import cards as C
from app.code import indexer as IDX
from app.db import get_db

log = logging.getLogger("nexus.routers.code")
router = APIRouter(prefix="/v1/code", tags=["code"])


# ── Schemas ─────────────────────────────────────────────────────────────

class IndexRepoRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    root_path: str = Field(min_length=1, max_length=1000)
    agent_id: Optional[str] = None
    max_files: int = Field(5000, le=50000)


class IrisGateRequest(BaseModel):
    symbol: Optional[str] = None
    file_path: Optional[str] = None
    rung: int = Field(2, ge=1, le=4)
    max_tokens: int = Field(2000, le=20000)
    justification: Optional[str] = None
    agent_id: Optional[str] = "default"


class BlastRequest(BaseModel):
    target: str
    depth: int = Field(2, ge=1, le=5)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/repos")
async def register_and_index_repo(
    body: IndexRepoRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Register a repo and index it.  Idempotent — existing repos re-index."""
    if not os.path.isdir(body.root_path):
        raise HTTPException(400, f"path not found: {body.root_path}")
    repo_id = await IDX.get_or_create_repo(db, body.name, body.root_path, body.agent_id)
    stats = await IDX.index_repo(db, repo_id, body.root_path, body.max_files)
    return {"repo_id": repo_id, **stats}


@router.get("/repos")
async def list_repos(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT id, name, root_path, agent_id, last_indexed_at, created_at
        FROM code_repos ORDER BY name
    """))).fetchall()
    return {"repos": [
        {
            "id": str(r[0]), "name": r[1], "root_path": r[2],
            "agent_id": r[3],
            "last_indexed_at": r[4].isoformat() if r[4] else None,
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]}


@router.get("/search")
async def search_symbols(
    repo_id: Optional[str] = None, q: str = Query(..., min_length=1),
    kind: Optional[str] = None, limit: int = Query(20, le=100),
    fmt: str = Query("auto", pattern="^(auto|json|compact)$"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Search symbols by name.  BM25-ish + trigram fuzzy.

    Add `?fmt=compact` to get the MUNCH compact wire format (path-
    interned, CSV-tagged).  Add `?fmt=json` to force verbose JSON.
    Default `auto` uses compact when savings >= 15%."""
    from app.code.munch import serialize_code_search
    if repo_id is None:
        repo_id = await _default_repo(db)
    syms = await C.search_symbols(db, repo_id, q, limit, kind)
    return serialize_code_search(
        {"repo_id": repo_id, "query": q, "symbols": syms, "count": len(syms)},
        fmt=fmt,
    )


@router.get("/symbol/{qualified_name:path}")
async def get_card(
    qualified_name: str,
    repo_id: Optional[str] = None,
    include_source: bool = False,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get one Symbol Card by qualified name."""
    if repo_id is None:
        repo_id = await _default_repo(db)
    card = await C.get_symbol_card(db, repo_id, qualified_name, include_source)
    if not card:
        raise HTTPException(404, f"symbol '{qualified_name}' not found")
    return card


@router.post("/iris")
async def iris_gate(
    body: IrisGateRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """The Iris Gate Ladder.  Returns code context at the requested rung.

    Rungs:
      1 - metadata only: just the symbol list
      2 - symbol cards: signatures, params, types (~100 tokens)
      3 - hot path: card + 80-line source preview
      4 - full source: card + complete body (requires justification)
    """
    if body.rung == 4 and not body.justification:
        raise HTTPException(400, "rung 4 (full source) requires justification")
    repo_id = body.repo_id if hasattr(body, "repo_id") else None
    if repo_id is None:
        repo_id = await _default_repo(db)
    return await C.iris_gate(
        db, repo_id, body.symbol, body.file_path, body.agent_id,
        body.rung, body.max_tokens, body.justification,
    )


@router.post("/blast")
async def blast(
    body: BlastRequest, fmt: str = Query("auto", pattern="^(auto|json|compact)$"),
    repo_id: Optional[str] = None, db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Blast radius: BFS through code_edges from a target symbol or file."""
    from app.code.munch import serialize_blast
    if repo_id is None:
        repo_id = await _default_repo(db)
    result = await C.blast_radius(db, repo_id, body.target, body.depth)
    return serialize_blast(result, fmt=fmt)


@router.get("/file/outline")
async def file_outline(
    path: str = Query(...), repo_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List all symbols in a file — like jcodemunch's outline tool."""
    if repo_id is None:
        repo_id = await _default_repo(db)
    out = await C.get_file_outline(db, repo_id, path)
    if not out:
        raise HTTPException(404, f"file '{path}' not indexed")
    return out


@router.post("/wiki/generate")
async def generate_wiki(
    repo_id: Optional[str] = None, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Generate the wiki knowledge map (`.nexus/wiki/` style)."""
    if repo_id is None:
        repo_id = await _default_repo(db)
    return await C.generate_wiki(db, repo_id)


@router.get("/wiki")
async def wiki_index(
    repo_id: Optional[str] = None,
    fmt: str = Query("auto", pattern="^(auto|json|compact)$"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Compact catalog (~200 tokens) of all wiki articles."""
    from app.code.munch import serialize_wiki_index
    if repo_id is None:
        repo_id = await _default_repo(db)
    articles = await C.list_wiki_index(db, repo_id)
    return serialize_wiki_index(
        {"repo_id": repo_id, "articles": articles, "count": len(articles)},
        fmt=fmt,
    )


@router.get("/wiki/{slug}")
async def wiki_article(
    slug: str, repo_id: Optional[str] = None, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    if repo_id is None:
        repo_id = await _default_repo(db)
    art = await C.get_wiki_article(db, repo_id, slug)
    if not art:
        raise HTTPException(404, f"wiki '{slug}' not found")
    return art


@router.get("/stats")
async def stats(repo_id: Optional[str] = None, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    if repo_id is None:
        repo_id = await _default_repo(db)
    counts = (await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM code_files WHERE repo_id = :rid) AS files,
            (SELECT COUNT(*) FROM code_symbols WHERE repo_id = :rid) AS symbols,
            (SELECT COUNT(*) FROM code_edges WHERE repo_id = :rid) AS edges,
            (SELECT COUNT(DISTINCT language) FROM code_files WHERE repo_id = :rid) AS langs,
            (SELECT COUNT(*) FROM code_wiki_articles WHERE repo_id = :rid) AS wiki
    """), {"rid": repo_id})).fetchone()
    runs = (await db.execute(text("""
        SELECT id, started_at, finished_at, files_indexed, symbols, edges, duration_ms
        FROM code_index_runs WHERE repo_id = :rid
        ORDER BY started_at DESC LIMIT 5
    """), {"rid": repo_id})).fetchall()
    audit = (await db.execute(text("""
        SELECT rung, COUNT(*) AS n
        FROM code_iris_audit WHERE repo_id = :rid
        GROUP BY rung ORDER BY rung
    """), {"rid": repo_id})).fetchall()
    return {
        "repo_id": repo_id,
        "files": counts[0], "symbols": counts[1], "edges": counts[2],
        "languages": counts[3], "wiki_articles": counts[4],
        "iris_usage": {r[0]: r[1] for r in audit},
        "recent_runs": [
            {
                "id": str(r[0]),
                "started_at": r[1].isoformat() if r[1] else None,
                "finished_at": r[2].isoformat() if r[2] else None,
                "files_indexed": r[3], "symbols": r[4], "edges": r[5],
                "duration_ms": r[6],
            } for r in runs
        ],
    }


# ── Helpers ─────────────────────────────────────────────────────────────

async def _default_repo(db: AsyncSession) -> str:
    row = (await db.execute(text("SELECT id FROM code_repos ORDER BY name LIMIT 1"))).fetchone()
    if not row:
        raise HTTPException(404, "no repos registered; POST /v1/code/repos first")
    return str(row[0])
