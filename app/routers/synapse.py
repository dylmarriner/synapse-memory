"""Synapse-compat routes — projects, file indexing, events, combined context."""

import hashlib
import json
import re
import logging
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db

log = logging.getLogger("nexus.routers.synapse")

router = APIRouter()

_LANG_MAP = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript-react",
    ".js": "javascript", ".jsx": "javascript-react", ".go": "go",
    ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".md": "markdown", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".sh": "shell", ".css": "css", ".html": "html",
    ".sql": "sql",
}

_SYMBOL_PATTERNS = [
    r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(",
    r"^\s*class\s+([A-Za-z_][\w]*)\b",
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
    r"^\s*(?:export\s+)?(?:interface|type|class)\s+([A-Za-z_$][\w$]*)\b",
    r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\(",
]


def _normalize_key(s: str) -> str:
    s = (s or "default").strip().lower()
    s = re.sub(r"[^a-z0-9_.-]+", "-", s).strip("-._")
    return s or "default"


def _detect_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _LANG_MAP.get(ext, ext.lstrip(".") or "text")


def _extract_symbols(text: str) -> list[str]:
    out: list[str] = []
    for pat in _SYMBOL_PATTERNS:
        out.extend(re.findall(pat, text, re.M))
    return sorted(set(out))[:200]


async def _ensure_project(db: AsyncSession, key: str, name: str | None = None) -> dict:
    key = _normalize_key(key)
    name = name or key
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO projects (id, key, name, created_at, updated_at)
            VALUES (gen_random_uuid(), :key, :name, :now, :now)
            ON CONFLICT (key) DO UPDATE SET
                name = COALESCE(NULLIF(:name2, ''), projects.name),
                updated_at = :now2
            RETURNING id, key, name, root, created_at, updated_at
        """),
        {"key": key, "name": name, "now": now, "name2": name, "now2": now},
    )
    await db.commit()
    row = await db.execute(
        text("SELECT id, key, name, root, created_at, updated_at FROM projects WHERE key = :key"),
        {"key": key},
    )
    r = row.fetchone()
    return dict(r._mapping) if r else {"key": key, "name": name}


# ── Project routes ───────────────────────────────────────────────────────────

@router.post("/projects/register")
async def register_project(key: str, name: str | None = None, root: str | None = None, db: AsyncSession = Depends(get_db)):
    """Register or update a project/workspace."""
    key = _normalize_key(key)
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO projects (id, key, name, root, created_at, updated_at)
            VALUES (gen_random_uuid(), :key, :name, :root, :now, :now)
            ON CONFLICT (key) DO UPDATE SET
                name = COALESCE(NULLIF(:name2, ''), projects.name),
                root = COALESCE(NULLIF(:root2, ''), projects.root),
                updated_at = :now2
        """),
        {"key": key, "name": name or key, "root": root, "now": now, "name2": name or "", "root2": root or "", "now2": now},
    )
    await db.execute(
        text("INSERT INTO events (id, project_key, actor, action, detail, created_at) VALUES (gen_random_uuid(), :pk, :actor, :action, :detail, :now)"),
        {"pk": key, "actor": "system", "action": "register_project", "detail": name or key, "now": now},
    )
    await db.commit()
    row = await db.execute(
        text("SELECT id, key, name, root, created_at, updated_at FROM projects WHERE key = :key"),
        {"key": key},
    )
    r = row.fetchone()
    return dict(r._mapping)


@router.get("/projects")
async def list_projects(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """List all registered projects."""
    rows = await db.execute(
        text("SELECT key, name, root, created_at, updated_at FROM projects ORDER BY updated_at DESC LIMIT :lim"),
        {"lim": max(1, min(200, limit))},
    )
    projects = [dict(r._mapping) for r in rows.fetchall()]
    return {"count": len(projects), "projects": projects}


# ── Memory routes (synapse-compat remember/recall signatures) ────────────────

@router.post("/projects/{project_key}/remember")
async def remember(
    project_key: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Store a memory with project-scoped upsert on (project_key, kind, title)."""
    key = _normalize_key(project_key)
    kind = _normalize_key(body.get("kind", "note"))
    title = body.get("title", "")
    content = (body.get("content") or "")[:200000]
    source = body.get("source", "agent")
    tags = body.get("tags")
    importance = max(1.0, min(5.0, float(body.get("importance", 3.0))))
    body_kind = _normalize_key(body.get("kind", "note"))
    now = datetime.now(timezone.utc)

    await _ensure_project(db, key)

    # Upsert via agent name = project scoped memory name
    agent_name = f"synapse-{key}"
    await db.execute(
        text("INSERT INTO agents (name, metadata) VALUES (:name, '{}'::jsonb) ON CONFLICT (name) DO NOTHING"),
        {"name": agent_name},
    )

    # Store as a nexus memory with tags and kind in metadata
    title_str = title.strip() or content[:80]
    tag_list = (tags or []) + [body_kind, f"synapse-project:{key}"]
    metadata_val = json.dumps({"tags": tag_list, "source": source, "kind": body_kind, "title": title_str})
    await db.execute(
        text("""
            INSERT INTO memories (agent_id, content, memory_type, importance, metadata, created_at, accessed_at)
            VALUES (
                (SELECT id FROM agents WHERE name = :agent_name),
                :content,
                :memory_type,
                :importance,
                CAST(:metadata AS jsonb),
                :now, :now
            )
        """),
        {
            "agent_name": agent_name,
            "content": f"{title_str}: {content}" if title else content,
            "memory_type": "observation",
            "importance": importance / 5.0,  # normalize synapse 1-5 to nexus 0-1
            "metadata": metadata_val,
            "now": now,
        },
    )
    await db.execute(
        text("INSERT INTO events (id, project_key, actor, action, detail, created_at) VALUES (gen_random_uuid(), :pk, :actor, :action, :detail, :now)"),
        {"pk": key, "actor": source, "action": "remember", "detail": f"{body_kind}:{title_str}", "now": now},
    )
    await db.commit()
    return {"project_key": key, "kind": body_kind, "title": title_str, "status": "saved"}


@router.post("/projects/{project_key}/recall")
async def recall(
    project_key: str = "default",
    body: dict = {},
    db: AsyncSession = Depends(get_db),
):
    """Search project memories by query/kind/tags."""
    key = _normalize_key(project_key)
    query = body.get("query", "")
    f_kind = body.get("kind")
    tags = body.get("tags")
    limit = max(1, min(50, int(body.get("limit", 10))))
    agent_name = f"synapse-{key}"

    conditions = ["a.name = :agent_name"]
    params = {"agent_name": agent_name}

    if f_kind:
        conditions.append("m.metadata->>'kind' = :kind")
        params["kind"] = _normalize_key(f_kind)
    if query.strip():
        q = f"%{query.strip()}%"
        conditions.append("(m.content ILIKE :q)")
        params["q"] = q
    if tags:
        for i, tag in enumerate(tags):
            conditions.append(f"m.metadata->'tags' ? :tag{i}")
            params[f"tag{i}"] = tag

    sql = f"""
        SELECT m.id, m.content, m.memory_type, m.importance, m.created_at,
               m.metadata, m.access_count
        FROM memories m
        JOIN agents a ON m.agent_id = a.id
        WHERE {' AND '.join(conditions)}
        ORDER BY m.importance DESC, m.created_at DESC
        LIMIT :lim
    """
    params["lim"] = limit
    rows = await db.execute(text(sql), params)
    results = []
    for r in rows.fetchall():
        d = dict(r._mapping)
        meta = d.get("metadata") or {}
        results.append({
            "id": str(d["id"]),
            "content": d["content"],
            "kind": meta.get("kind", d["memory_type"]),
            "title": meta.get("title", ""),
            "importance": d["importance"],
            "source": meta.get("source", "agent"),
            "tags": meta.get("tags", []),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else "",
        })
    return {"project_key": key, "count": len(results), "memories": results}


# ── File indexing routes ─────────────────────────────────────────────────────

@router.post("/projects/{project_key}/files/ingest")
async def ingest_file(
    project_key: str, path: str, db: AsyncSession = Depends(get_db),
):
    """Index a file: hash, detect language, extract symbols."""
    key = _normalize_key(project_key)
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    text_content = p.read_text(errors="replace")[:200000]
    sha = hashlib.sha256(text_content.encode("utf-8", "replace")).hexdigest()
    lang = _detect_language(str(p))
    symbols = _extract_symbols(text_content)
    lines = [line.strip() for line in text_content.splitlines() if line.strip()][:20]
    summary = "\n".join(lines)[:2000]
    now = datetime.now(timezone.utc)

    await _ensure_project(db, key)
    await db.execute(
        text("""
            INSERT INTO file_index (id, project_key, path, sha256, size, language, summary, symbols, updated_at)
            VALUES (gen_random_uuid(), :pk, :path, :sha, :size, :lang, :summary, :symbols, :now)
            ON CONFLICT (project_key, path) DO UPDATE SET
                sha256 = :sha2, size = :size2, language = :lang2,
                summary = :summary2, symbols = :symbols2, updated_at = :now2
        """),
        {
            "pk": key, "path": str(p), "sha": sha, "size": len(text_content),
            "lang": lang, "summary": summary, "symbols": json.dumps(symbols), "now": now,
            "sha2": sha, "size2": len(text_content), "lang2": lang,
            "summary2": summary, "symbols2": json.dumps(symbols), "now2": now,
        },
    )
    await db.execute(
        text("INSERT INTO events (id, project_key, actor, action, detail, created_at) VALUES (gen_random_uuid(), :pk, :actor, :action, :detail, :now)"),
        {"pk": key, "actor": "agent", "action": "ingest_file", "detail": str(p), "now": now},
    )
    await db.commit()
    return {"project_key": key, "path": str(p), "sha256": sha, "language": lang, "symbols": json.dumps(symbols)}


@router.post("/projects/{project_key}/files/search")
async def search_project_files(
    project_key: str = "default",
    query: str = "",
    language: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Search indexed files by query/language."""
    key = _normalize_key(project_key)
    limit = max(1, min(100, int(limit)))
    conditions = ["project_key = :pk"]
    params = {"pk": key}
    if language:
        conditions.append("language = :lang")
        params["lang"] = language
    if query.strip():
        q = f"%{query.strip()}%"
        conditions.append("(path ILIKE :q OR summary ILIKE :q2 OR symbols::text ILIKE :q3)")
        params.update({"q": q, "q2": q, "q3": q})
    params["lim"] = limit
    rows = await db.execute(
        text(f"SELECT id, path, sha256, size, language, summary, symbols, updated_at FROM file_index WHERE {' AND '.join(conditions)} ORDER BY updated_at DESC LIMIT :lim"),
        params,
    )
    files = [dict(r._mapping) for r in rows.fetchall()]
    return {"project_key": key, "count": len(files), "files": files}


# ── Combined context route ───────────────────────────────────────────────────

@router.get("/projects/{project_key}/context")
async def project_context(
    project_key: str = "default",
    query: str = "",
    limit: int = 12,
    db: AsyncSession = Depends(get_db),
):
    """Return compact context pack: project info + relevant memories + files."""
    key = _normalize_key(project_key)
    proj = await db.execute(
        text("SELECT key, name, root, created_at, updated_at FROM projects WHERE key = :key"),
        {"key": key},
    )
    project_row = proj.fetchone()

    memories_resp = await recall(project_key=key, body={"query": query, "limit": limit}, db=db)
    files_resp = await search_project_files(project_key=key, query=query, limit=limit, db=db)

    return {
        "project": dict(project_row._mapping) if project_row else {"key": key},
        "query": query,
        "memories": memories_resp["memories"],
        "files": files_resp["files"],
    }


# ── Events / activity routes ────────────────────────────────────────────────

@router.get("/projects/{project_key}/events")
async def recent_activity(
    project_key: str = "default",
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List recent events for a project."""
    key = _normalize_key(project_key)
    rows = await db.execute(
        text("SELECT id, actor, action, detail, created_at FROM events WHERE project_key = :pk ORDER BY created_at DESC LIMIT :lim"),
        {"pk": key, "lim": max(1, min(100, int(limit)))},
    )
    events = [dict(r._mapping) for r in rows.fetchall()]
    return {"project_key": key, "count": len(events), "events": events}


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health/synapse")
async def synapse_health(db: AsyncSession = Depends(get_db)):
    """Health check for synapse-compat subsystem."""
    pcount = (await db.execute(text("SELECT COUNT(*) FROM projects"))).scalar() or 0
    fcount = (await db.execute(text("SELECT COUNT(*) FROM file_index"))).scalar() or 0
    ecount = (await db.execute(text("SELECT COUNT(*) FROM events"))).scalar() or 0
    return {"ok": True, "projects": pcount, "files": fcount, "events": ecount}
