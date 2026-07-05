"""Memory ↔ Code-symbol linking.

A memory can be attached to one or more code symbols (or files, or
raw text references).  The link carries a `source` field that records
how the link was made:

  - manual: a user explicitly attached the memory to the symbol
  - auto_extract: the memory content mentioned a known symbol name
  - mind_inject: the Living Mind auto-attached the memory while reasoning
  - user_feedback: created via the natural-language feedback endpoint

This module also exposes "find memories that reference this symbol"
so the dashboard can show a memory's related code on hover, and the
mind can recall memories by symbol when asked.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.code.links")


# ── Create links ──────────────────────────────────────────────────────

async def link_memory_to_symbol(
    db: AsyncSession,
    memory_id: str,
    code_symbol_id: str,
    source: str = "auto_extract",
    confidence: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Link a memory to a specific code symbol. Idempotent on
    (memory_id, code_symbol_id)."""
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO memory_code_links
            (id, memory_id, code_symbol_id, source, confidence, metadata)
        SELECT :id, :mid, :sid, :source, :conf, CAST(:meta AS jsonb)
        WHERE NOT EXISTS (
            SELECT 1 FROM memory_code_links
            WHERE memory_id = :mid AND code_symbol_id = :sid
        )
        RETURNING id
    """), {
        "id": new_id, "mid": memory_id, "sid": code_symbol_id,
        "source": source, "conf": confidence,
        "meta": _json(metadata or {}),
    })
    await db.commit()
    return new_id


async def link_memory_to_file(
    db: AsyncSession,
    memory_id: str,
    code_file_id: str,
    source: str = "manual",
    confidence: float = 0.4,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Link a memory to a file (when no exact symbol matches)."""
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO memory_code_links
            (id, memory_id, code_file_id, source, confidence, metadata)
        SELECT :id, :mid, :fid, :source, :conf, CAST(:meta AS jsonb)
        WHERE NOT EXISTS (
            SELECT 1 FROM memory_code_links
            WHERE memory_id = :mid AND code_file_id = :fid
        )
        RETURNING id
    """), {
        "id": new_id, "mid": memory_id, "fid": code_file_id,
        "source": source, "conf": confidence,
        "meta": _json(metadata or {}),
    })
    await db.commit()
    return new_id


async def link_memory_to_raw(
    db: AsyncSession,
    memory_id: str,
    code_repo_id: str,
    raw_text: str,
    source: str = "auto_extract",
    confidence: float = 0.3,
) -> str:
    """Link a memory to a raw text reference (e.g. "the sync script")."""
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO memory_code_links
            (id, memory_id, code_repo_id, raw_text, source, confidence)
        VALUES (:id, :mid, :rid, :raw, :source, :conf)
        ON CONFLICT DO NOTHING
    """), {
        "id": new_id, "mid": memory_id, "rid": code_repo_id,
        "raw": raw_text, "source": source, "conf": confidence,
    })
    await db.commit()
    return new_id


# ── Query links ───────────────────────────────────────────────────────

async def find_memories_for_symbol(
    db: AsyncSession,
    repo_id: str,
    qualified_name: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Get all memories linked to a specific code symbol."""
    rows = (await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance, m.confidence,
               m.access_count, m.created_at, mcl.source, mcl.confidence AS link_confidence
        FROM memory_code_links mcl
        JOIN memories m ON m.id = mcl.memory_id
        WHERE mcl.code_repo_id = :rid
          AND (
            mcl.code_symbol_id = (
                SELECT id FROM code_symbols
                WHERE repo_id = :rid AND qualified_name = :qn
                LIMIT 1
            )
            OR mcl.raw_text = :qn
            OR mcl.code_file_id = (
                SELECT id FROM code_files
                WHERE repo_id = :rid AND rel_path = :qn
                LIMIT 1
            )
          )
        ORDER BY mcl.confidence DESC, m.importance DESC
        LIMIT :limit
    """), {"rid": repo_id, "qn": qualified_name, "limit": limit})).fetchall()
    return [
        {
            "id": str(r[0]),
            "content": r[1],
            "memory_type": r[2],
            "importance": float(r[3] or 0),
            "confidence": float(r[4] or 0),
            "access_count": r[5] or 0,
            "created_at": r[6].isoformat() if r[6] else None,
            "link_source": r[7],
            "link_confidence": float(r[8] or 0),
        }
        for r in rows
    ]


async def find_symbols_for_memory(
    db: AsyncSession,
    memory_id: str,
) -> List[Dict[str, Any]]:
    """Get all code symbols linked to a specific memory."""
    rows = (await db.execute(text("""
        SELECT s.id, s.name, s.qualified_name, s.kind, s.signature, s.docstring,
               f.path, s.start_line, s.end_line, mcl.source, mcl.confidence
        FROM memory_code_links mcl
        JOIN code_symbols s ON s.id = mcl.code_symbol_id
        JOIN code_files f ON f.id = s.file_id
        WHERE mcl.memory_id = :mid
        ORDER BY mcl.confidence DESC
    """), {"mid": memory_id})).fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "qualified_name": r[2],
            "kind": r[3],
            "signature": r[4] or "",
            "docstring": r[5] or "",
            "path": r[6],
            "start_line": r[7],
            "end_line": r[8],
            "link_source": r[9],
            "link_confidence": float(r[10] or 0),
        }
        for r in rows
    ]


# ── Auto-extract on save ────────────────────────────────────────────

# Pattern matches dotted/CamelCase/snake_case identifiers that look like
# function or class names.  We don't try to be perfect — the indexer's
# search endpoint is the source of truth; this just finds candidate
# symbol names to attempt resolution.
_CODE_TOKEN = re.compile(r"\b([A-Za-z_][\w]{2,}(?:\.[A-Za-z_]\w+)+|[A-Z][\w]*(?:[A-Z]\w+|_\w+)+|[a-z_]\w+_\w+)\b")


async def auto_link_memory_to_symbols(
    db: AsyncSession,
    memory_id: str,
    memory_content: str,
    repo_id: Optional[str] = None,
    max_links: int = 5,
) -> List[str]:
    """Scan the memory content for symbol-like tokens and link each
    one that resolves in the code index.  Returns the created link IDs.
    """
    if not memory_content:
        return []
    # Pull a default repo if none given
    if repo_id is None:
        row = (await db.execute(text("SELECT id FROM code_repos ORDER BY name LIMIT 1"))).fetchone()
        if not row:
            return []
        repo_id = str(row[0])
    # Extract candidate tokens (qualified names like Class.method, CamelCase, snake)
    candidates = set()
    for m in _CODE_TOKEN.finditer(memory_content or ""):
        candidates.add(m.group(1))
    if not candidates:
        return []
    # Look up each in the code index
    link_ids: List[str] = []
    for cand in list(candidates)[:max_links * 3]:
        row = (await db.execute(text("""
            SELECT id FROM code_symbols
            WHERE repo_id = :rid AND (qualified_name = :q OR name = :q)
            LIMIT 1
        """), {"rid": repo_id, "q": cand})).fetchone()
        if not row:
            continue
        try:
            lid = await link_memory_to_symbol(
                db, memory_id, str(row[0]),
                source="auto_extract", confidence=0.4,
            )
            link_ids.append(lid)
        except Exception as e:
            log.debug("auto-link %s -> %s failed: %s", memory_id, cand, e)
        if len(link_ids) >= max_links:
            break
    return link_ids


def _json(obj) -> str:
    import json
    return json.dumps(obj, default=str)


__all__ = [
    "link_memory_to_symbol", "link_memory_to_file", "link_memory_to_raw",
    "find_memories_for_symbol", "find_symbols_for_memory",
    "auto_link_memory_to_symbols",
]
