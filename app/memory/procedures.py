"""Procedural memory — compacting how-to knowledge per project."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.memory.procedures")

_COMPACT_PROMPT = """You are compacting procedural knowledge for project "{project_key}".
Synthesize the following procedure memories into one tight "HOW TO WORK HERE" document.
Format: bullet points grouped by category (Testing, Deploy, Commands, Gotchas, etc.).
Be terse. Max 500 words. Deduplicate. Preserve all commands exactly.

PROCEDURES:
{content}"""


async def compact_project_procedures(
    db: AsyncSession,
    project_key: str,
    llm,
) -> Optional[str]:
    """Synthesize uncompacted procedure memories for a project into one document.

    Returns the compacted content string, or None if skipped.
    """
    from app.config import settings

    # Find uncompacted procedure memories for this project.
    rows = await db.execute(text("""
        SELECT id, content, importance
        FROM memories
        WHERE memory_type = 'procedure'
          AND superseded_by IS NULL
          AND COALESCE(metadata->>'compacted', 'false') != 'true'
          AND COALESCE(metadata->>'project_key', '') = :pk
        ORDER BY importance DESC, created_at ASC
        LIMIT 50
    """), {"pk": project_key})
    procs = rows.fetchall()

    if len(procs) < 5:
        return None

    combined = "\n\n".join(f"- {r.content}" for r in procs)
    prompt = _COMPACT_PROMPT.format(project_key=project_key, content=combined[:4000])

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=settings.llm_synthesis_max_tokens,
            temperature=0,
        )
        compacted = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning("Procedure compaction LLM call failed for %s: %s", project_key, e)
        return None

    if not compacted:
        return None

    # Save the compacted memory.
    new_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    meta = json.dumps({
        "compacted": True,
        "project_key": project_key,
        "source_count": len(procs),
        "compacted_at": now.isoformat(),
    })
    await db.execute(text("""
        INSERT INTO memories
            (id, content, memory_type, importance, metadata, confidence, created_at, accessed_at)
        VALUES
            (:id, :content, 'procedure', 0.95, CAST(:meta AS jsonb), 1.0, :now, :now)
    """), {"id": new_id, "content": compacted, "meta": meta, "now": now})

    # Supersede the individual ones.
    for r in procs:
        await db.execute(text("""
            UPDATE memories
            SET superseded_by = :new_id,
                metadata = COALESCE(metadata, '{}'::jsonb) || '{"compacted": true}'::jsonb
            WHERE id = :old_id
        """), {"new_id": new_id, "old_id": r.id})

    await db.commit()
    log.info("Compacted %d procedures for project %s → %s", len(procs), project_key, str(new_id)[:8])
    return compacted


async def get_project_procedures(db: AsyncSession, project_key: str) -> list:
    """Return the compacted procedure document for a project, or individual ones."""
    # Prefer compacted doc.
    compacted = await db.execute(text("""
        SELECT id, content, importance, created_at
        FROM memories
        WHERE memory_type = 'procedure'
          AND superseded_by IS NULL
          AND COALESCE(metadata->>'compacted', 'false') = 'true'
          AND COALESCE(metadata->>'project_key', '') = :pk
        ORDER BY created_at DESC
        LIMIT 1
    """), {"pk": project_key})
    row = compacted.fetchone()
    if row:
        return [{"id": str(row.id), "content": row.content, "compacted": True}]

    # Fall back to individual uncompacted procedures.
    rows = await db.execute(text("""
        SELECT id, content, importance, created_at
        FROM memories
        WHERE memory_type = 'procedure'
          AND superseded_by IS NULL
          AND COALESCE(metadata->>'project_key', '') = :pk
        ORDER BY importance DESC, created_at DESC
        LIMIT 20
    """), {"pk": project_key})
    return [{"id": str(r.id), "content": r.content, "compacted": False} for r in rows.fetchall()]
