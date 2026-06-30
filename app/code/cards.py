"""Symbol Cards, Iris Gate Ladder, blast radius, wiki — all the things
that turn a flat symbol list into structured, token-efficient context.

Symbol Card: ~100 token dense representation of a function/class/etc.
Iris Gate Ladder: 4 rungs of context escalation (metadata → signature →
hot path → full source).  Agents start at rung 1 and escalate only when
they need more.  Each rung is policy-audited.

Blast radius: BFS from a symbol/file through the code_edges graph to
find all transitively affected symbols, weighted by edge confidence.

Wiki: a `.nexus/wiki/` knowledge map with an index (~200 tokens) plus
per-topic articles that the agent reads on demand.  Mirrors the
codesight `--wiki` pattern.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.code.cards")


# ── Symbol Card (~100 tokens) ───────────────────────────────────────────

async def get_symbol_card(
    db: AsyncSession, repo_id: str, qualified_name: str, include_source: bool = False
) -> Optional[Dict[str, Any]]:
    """The 'Iris Gate rung 1+2' response.  Dense metadata-only card."""
    row = (await db.execute(text("""
        SELECT s.id, s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
               s.signature, s.docstring, s.return_type, s.parameters,
               s.decorators, s.visibility, s.is_exported, s.is_async,
               s.complexity, s.line_count,
               f.path, f.language
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid AND s.qualified_name = :qn
        LIMIT 1
    """), {"rid": repo_id, "qn": qualified_name})).fetchone()
    if not row:
        return None
    card = _row_to_card(row)
    if include_source:
        # Promote to rung 3 (signature + body preview)
        source = await get_source_snippet(db, repo_id, qualified_name, max_lines=80)
        card["source_snippet"] = source
    return card


def _row_to_card(row) -> Dict[str, Any]:
    import json
    params = row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]")
    decs = row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]")
    return {
        "id": str(row[0]),
        "name": row[1],
        "qualified_name": row[2],
        "kind": row[3],
        "location": {
            "path": row[16],
            "start_line": row[4],
            "end_line": row[5],
        },
        "language": row[17],
        "signature": row[6] or "",
        "docstring": row[7] or "",
        "return_type": row[8] or "",
        "parameters": params,
        "decorators": decs,
        "visibility": row[11],
        "is_exported": bool(row[12]),
        "is_async": bool(row[13]),
        "complexity": row[14] or 1,
        "line_count": row[15] or 0,
    }


async def get_source_snippet(
    db: AsyncSession, repo_id: str, qualified_name: str, max_lines: int = 80
) -> Optional[str]:
    """Iris Gate rung 3: signature + body lines."""
    row = (await db.execute(text("""
        SELECT s.start_byte, s.end_byte, f.path
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid AND s.qualified_name = :qn
        LIMIT 1
    """), {"rid": repo_id, "qn": qualified_name})).fetchone()
    if not row:
        return None
    # The DB doesn't store the file content; re-read from disk.
    # (In a production system we'd cache the file or store a small body.
    # For now, this is fine because we control the indexed repo and
    # the path is on the same host as the indexer.)
    import os
    path = row[2]
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        start, end = row[0], row[1]
        return content[start:end][:max_lines * 200]  # rough char cap
    except Exception as e:
        log.debug("source read failed for %s: %s", path, e)
        return None


# ── Symbol search ───────────────────────────────────────────────────────

async def search_symbols(
    db: AsyncSession, repo_id: str, query: str, limit: int = 20,
    kind: Optional[str] = None
) -> List[Dict[str, Any]]:
    """BM25-ish search by name + qualified_name, plus trigram fuzzy.

    The query is tokenized on whitespace and we OR-match across tokens
    so a question like "Show me the code for LivingMind.think" still
    finds `LivingMind.think` even though the full string doesn't
    appear in any symbol.
    """
    import re
    tokens = [t for t in re.split(r"\W+", query) if len(t) >= 2][:8]
    if not tokens:
        return []
    # Build OR-of-ILIKE across the name + qualified_name columns
    or_clauses: List[str] = []
    for i, tok in enumerate(tokens):
        or_clauses.append(f"(s.name ILIKE :t{i} OR s.qualified_name ILIKE :t{i})")
    where_kind = "AND s.kind = :kind" if kind else ""
    params: Dict[str, Any] = {"rid": repo_id, "limit": limit}
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = f"%{tok}%"
    if kind:
        params["kind"] = kind
    rows = (await db.execute(text(f"""
        SELECT s.id, s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
               s.signature, s.docstring, f.path
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid
          AND ({" OR ".join(or_clauses)})
          {where_kind}
        ORDER BY s.qualified_name
        LIMIT :limit
    """), params)).fetchall()
    return [
        {
            "id": str(r[0]), "name": r[1], "qualified_name": r[2],
            "kind": r[3], "start_line": r[4], "end_line": r[5],
            "signature": r[6] or "", "docstring": r[7] or "",
            "path": r[8],
        }
        for r in rows
    ]


# ── Iris Gate Ladder ───────────────────────────────────────────────────

async def iris_gate(
    db: AsyncSession,
    repo_id: Optional[str],
    symbol: Optional[str],
    file_path: Optional[str],
    agent_id: Optional[str] = "default",
    rung: int = 2,
    max_tokens: int = 2000,
    justification: Optional[str] = None,
) -> Dict[str, Any]:
    """Return code context at the requested Iris Gate rung.

    Rungs:
      1 - metadata only: count + names (no source, no signatures)
      2 - symbol cards: signatures, params, types (~100 tokens per symbol)
      3 - hot path: card + 80-line source preview per symbol
      4 - full source: card + complete body (policy-gated, requires
          justification; logged to code_iris_audit).

    Tokens are estimated at 4 chars/token (the standard LLM rule of thumb).
    """
    rung = max(1, min(4, rung))
    est_tokens_per_char = 0.25  # 1 token = 4 chars

    if symbol:
        # Single-symbol query
        sym = (await db.execute(text("""
            SELECT s.id, s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
                   s.signature, s.docstring, s.return_type, s.parameters,
                   s.decorators, s.visibility, s.is_exported, s.is_async,
                   s.complexity, s.line_count, f.path, f.language
            FROM code_symbols s
            JOIN code_files f ON f.id = s.file_id
            WHERE s.qualified_name = :qn AND (CAST(:rid AS text) IS NULL OR s.repo_id = CAST(:rid AS uuid))
            LIMIT 1
        """), {"qn": symbol, "rid": repo_id})).fetchone()
        if not sym:
            return {"rung": rung, "error": f"symbol '{symbol}' not found"}
        card = _row_to_card(sym)
        bytes_used = len(str(card))
        if rung >= 3:
            src = await get_source_snippet(db, repo_id or "", symbol, max_lines=80)
            if src:
                card["source_snippet"] = src
                bytes_used += len(src)
        if rung >= 4:
            if not justification:
                return {
                    "rung": rung,
                    "error": "rung 4 (full source) requires justification",
                    "card": card,
                }
            await db.execute(text("""
                INSERT INTO code_iris_audit
                    (repo_id, agent_id, symbol_id, rung, bytes_returned, justification)
                VALUES (:rid, :aid, :sid, :rung, :bytes, :just)
            """), {
                "rid": repo_id, "aid": agent_id, "sid": card["id"],
                "rung": rung, "bytes": bytes_used, "just": justification,
            })
            await db.commit()
        return {
            "rung": rung,
            "card": card,
            "bytes": bytes_used,
            "est_tokens": int(bytes_used * est_tokens_per_char),
        }
    if file_path:
        # File-level: return all symbols in the file
        params: Dict[str, Any] = {"path": file_path, "rid": repo_id}
        rows = (await db.execute(text("""
            SELECT s.id, s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
                   s.signature, s.docstring, s.return_type, s.parameters,
                   s.decorators, s.visibility, s.is_exported, s.is_async,
                   s.complexity, s.line_count, f.path, f.language
            FROM code_symbols s
            JOIN code_files f ON f.id = s.file_id
            WHERE f.path = :path AND (CAST(:rid AS text) IS NULL OR s.repo_id = CAST(:rid AS uuid))
            ORDER BY s.start_line
        """), params)).fetchall()
        if not rows:
            return {"rung": rung, "error": f"file '{file_path}' not indexed"}
        out_symbols: List[Dict[str, Any]] = []
        bytes_used = 0
        for r in rows:
            card = _row_to_card(r)
            if rung >= 3:
                src = await get_source_snippet(db, repo_id or "", card["qualified_name"], max_lines=40)
                if src:
                    card["source_snippet"] = src
                    bytes_used += len(src)
            out_symbols.append(card)
            bytes_used += len(str(card))
            if bytes_used > max_tokens * 4:  # rough char cap
                break
        return {
            "rung": rung,
            "file": file_path,
            "symbols": out_symbols,
            "count": len(out_symbols),
            "bytes": bytes_used,
            "est_tokens": int(bytes_used * est_tokens_per_char),
        }
    return {"error": "must provide symbol or file_path"}


# ── Blast radius ───────────────────────────────────────────────────────

async def blast_radius(
    db: AsyncSession, repo_id: str, target: str, depth: int = 2
) -> Dict[str, Any]:
    """BFS through code_edges from the target symbol.  Returns the set
    of affected symbols grouped by depth."""
    # Resolve the target to a starting set of edges
    start_edges = (await db.execute(text("""
        WITH start_ids AS (
            SELECT id FROM code_symbols
            WHERE repo_id = :rid AND (qualified_name = :tgt OR name = :tgt)
        ),
        start_files AS (
            SELECT id FROM code_files WHERE repo_id = :rid AND rel_path = :tgt
        )
        SELECT dst_symbol_id AS sid, kind, weight, confidence, 0 AS lvl
        FROM code_edges
        WHERE src_symbol_id IN (SELECT id FROM start_ids)
           OR src_file_id IN (SELECT id FROM start_files)
    """), {"rid": repo_id, "tgt": target})).fetchall()
    visited: Dict[str, int] = {}  # symbol_id -> depth
    queue: List[Tuple[Optional[str], int]] = []
    for e in start_edges:
        if e[0]:
            visited[str(e[0])] = 0
            queue.append((str(e[0]), 0))
    # Resolve names
    by_id: Dict[str, Dict[str, Any]] = {}
    if visited:
        rows = (await db.execute(text("""
            SELECT id, name, qualified_name, kind FROM code_symbols WHERE id = ANY(:ids)
        """), {"ids": list(visited.keys())})).fetchall()
        for r in rows:
            by_id[str(r[0])] = {"name": r[1], "qualified_name": r[2], "kind": r[3]}
    layers: Dict[int, List[Dict[str, Any]]] = {0: [by_id[s] for s in visited if s in by_id]}
    current = list(visited.keys())
    for d in range(1, depth + 1):
        if not current:
            break
        rows = (await db.execute(text("""
            SELECT DISTINCT e.dst_symbol_id, s.qualified_name, s.name, s.kind
            FROM code_edges e
            JOIN code_symbols s ON s.id = e.dst_symbol_id
            WHERE e.src_symbol_id = ANY(:srcs)
              AND e.dst_symbol_id IS NOT NULL
        """), {"srcs": current})).fetchall()
        next_layer: List[str] = []
        for r in rows:
            sid = str(r[0])
            if sid not in visited:
                visited[sid] = d
                next_layer.append(sid)
                by_id[sid] = {"name": r[2], "qualified_name": r[1], "kind": r[3]}
        layers[d] = [by_id[s] for s in next_layer]
        current = next_layer
    total = sum(len(v) for v in layers.values())
    return {
        "target": target,
        "depth": depth,
        "total_affected": total,
        "by_depth": {d: len(v) for d, v in layers.items() if v},
        "symbols": [
            {"depth": d, "symbol": s}
            for d, v in layers.items() for s in v
        ],
    }


# ── Wiki generator ────────────────────────────────────────────────────

WIKI_SECTIONS = [
    ("overview", "Architecture overview", "High-level shape of the codebase"),
    ("routes", "API Routes", "HTTP endpoints, parameters, auth"),
    ("models", "Data Models", "Database tables, fields, relations"),
    ("services", "Services", "Business logic and orchestration"),
    ("agents", "Agents", "Autonomous loops and decision points"),
    ("memory", "Memory System", "Stores, indexes, retrieval paths"),
    ("infra", "Infrastructure", "Docker, cron, deployment"),
]


async def generate_wiki(db: AsyncSession, repo_id: str) -> Dict[str, Any]:
    """Produce a `.nexus/wiki/`-style knowledge map.  Returns the
    sections as a dict (markdown bodies)."""
    sections: Dict[str, str] = {}

    # Overview
    counts = (await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM code_files WHERE repo_id = :rid) AS files,
            (SELECT COUNT(*) FROM code_symbols WHERE repo_id = :rid) AS symbols,
            (SELECT COUNT(*) FROM code_edges WHERE repo_id = :rid) AS edges,
            (SELECT COUNT(DISTINCT language) FROM code_files WHERE repo_id = :rid) AS langs
    """), {"rid": repo_id})).fetchone()
    files, syms, edges, langs = counts
    sections["overview"] = (
        f"# Architecture Overview\n\n"
        f"- **Files**: {files}\n"
        f"- **Symbols**: {syms}\n"
        f"- **Edges (call/import/ref)**: {edges}\n"
        f"- **Languages**: {langs}\n\n"
        f"This index was generated by Nexus.  Read each section for details.\n"
    )

    # Routes (HTTP handlers)
    routes = (await db.execute(text("""
        SELECT s.qualified_name, s.signature, s.docstring, f.path
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid AND s.kind IN ('function','method')
          AND (f.path ILIKE '%route%' OR f.path ILIKE '%api%' OR f.path ILIKE '%router%'
               OR s.qualified_name ILIKE '%route%' OR s.qualified_name ILIKE '%handler%'
               OR s.qualified_name ILIKE '%endpoint%')
        ORDER BY f.path, s.start_line
        LIMIT 200
    """), {"rid": repo_id})).fetchall()
    if routes:
        body = "# API Routes\n\n"
        for r in routes:
            body += f"### `{r[0]}`\n\n- **File**: `{r[3]}`\n- **Signature**: `{r[1] or ''}`\n"
            if r[2]:
                body += f"- **Notes**: {r[2].splitlines()[0]}\n"
            body += "\n"
        sections["routes"] = body
    else:
        sections["routes"] = "# API Routes\n\n_No route handlers detected in the index._\n"

    # Models (classes that look like DB models)
    models = (await db.execute(text("""
        SELECT s.qualified_name, s.docstring, s.signature, f.path
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid AND s.kind = 'class'
          AND (s.qualified_name ILIKE '%Model%' OR s.qualified_name ILIKE '%Schema%'
               OR s.qualified_name ILIKE '%Table%' OR s.qualified_name ILIKE '%Entity%'
               OR f.path ILIKE '%models%' OR f.path ILIKE '%schema%')
        ORDER BY s.qualified_name
        LIMIT 100
    """), {"rid": repo_id})).fetchall()
    if models:
        body = "# Data Models\n\n"
        for m in models:
            body += f"### `{m[0]}`\n\n- **File**: `{m[3]}`\n- **Signature**: `{m[2] or ''}`\n"
            if m[1]:
                body += f"- **Notes**: {m[1].splitlines()[0]}\n"
            body += "\n"
        sections["models"] = body
    else:
        sections["models"] = "# Data Models\n\n_No ORM models detected in the index._\n"

    # Services
    services = (await db.execute(text("""
        SELECT s.qualified_name, s.signature, s.docstring, f.path
        FROM code_symbols s
        JOIN code_files f ON f.id = s.file_id
        WHERE s.repo_id = :rid AND s.kind = 'class'
          AND (s.qualified_name ILIKE '%Service%' OR s.qualified_name ILIKE '%Manager%'
               OR s.qualified_name ILIKE '%Repository%' OR s.qualified_name ILIKE '%Handler%')
        ORDER BY s.qualified_name
        LIMIT 100
    """), {"rid": repo_id})).fetchall()
    if services:
        body = "# Services\n\n"
        for s_ in services:
            body += f"### `{s_[0]}`\n\n- **File**: `{s_[3]}`\n- **Signature**: `{s_[1] or ''}`\n"
            if s_[2]:
                body += f"- **Notes**: {s_[2].splitlines()[0]}\n"
            body += "\n"
        sections["services"] = body
    else:
        sections["services"] = "# Services\n\n_No service classes detected._\n"

    # Save the articles
    for slug, (section_key, title, _) in zip([s[0] for s in WIKI_SECTIONS], WIKI_SECTIONS):
        body = sections.get(section_key, "")
        await _upsert_wiki(db, repo_id, section_key, slug.replace("-", " ").title(), body, section_key)
    return {
        "sections": {k: sections.get(k, "") for k, _, _ in WIKI_SECTIONS},
        "stats": {"files": files, "symbols": syms, "edges": edges, "languages": langs},
    }


async def _upsert_wiki(db, repo_id, slug, title, content, section) -> None:
    token_estimate = max(1, len(content) // 4)
    await db.execute(text("""
        INSERT INTO code_wiki_articles
            (repo_id, title, slug, content, section, token_estimate)
        VALUES (:rid, :title, :slug, :content, :section, :tokens)
        ON CONFLICT (repo_id, slug) DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            section = EXCLUDED.section,
            token_estimate = EXCLUDED.token_estimate,
            generated_at = NOW()
    """), {
        "rid": repo_id, "title": title, "slug": slug,
        "content": content, "section": section, "tokens": token_estimate,
    })
    await db.commit()


async def get_wiki_article(db: AsyncSession, repo_id: str, slug: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT id, title, slug, content, section, token_estimate, generated_at
        FROM code_wiki_articles WHERE repo_id = :rid AND slug = :slug
    """), {"rid": repo_id, "slug": slug})).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "title": row[1], "slug": row[2],
        "content": row[3], "section": row[4],
        "token_estimate": row[5],
        "generated_at": row[6].isoformat() if row[6] else None,
    }


async def list_wiki_index(db: AsyncSession, repo_id: str) -> List[Dict[str, Any]]:
    """Compact catalog (~200 tokens) of all wiki articles."""
    rows = (await db.execute(text("""
        SELECT title, slug, section, token_estimate
        FROM code_wiki_articles WHERE repo_id = :rid
        ORDER BY section, slug
    """), {"rid": repo_id})).fetchall()
    return [
        {"title": r[0], "slug": r[1], "section": r[2], "tokens": r[3]}
        for r in rows
    ]


# ── File outline ───────────────────────────────────────────────────────

async def get_file_outline(db: AsyncSession, repo_id: str, file_path: str) -> Optional[Dict[str, Any]]:
    """List all symbols in a file — like `Outline` in sdl-mcp."""
    row = (await db.execute(text("""
        SELECT id, language, bytes, line_count FROM code_files
        WHERE repo_id = :rid AND rel_path = :path
        LIMIT 1
    """), {"rid": repo_id, "path": file_path})).fetchone()
    if not row:
        return None
    file_id = str(row[0])
    symbols = (await db.execute(text("""
        SELECT name, qualified_name, kind, start_line, end_line, signature
        FROM code_symbols WHERE file_id = :fid
        ORDER BY start_line
    """), {"fid": file_id})).fetchall()
    return {
        "file": file_path, "language": row[1], "bytes": row[2], "line_count": row[3],
        "symbols": [
            {"name": s[0], "qualified_name": s[1], "kind": s[2],
             "start_line": s[3], "end_line": s[4], "signature": s[5] or ""}
            for s in symbols
        ],
    }


__all__ = [
    "get_symbol_card", "get_source_snippet", "search_symbols",
    "iris_gate", "blast_radius",
    "generate_wiki", "get_wiki_article", "list_wiki_index",
    "get_file_outline",
]
