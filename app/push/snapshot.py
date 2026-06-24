"""Build a compact context snapshot for injection into agent config files.

The snapshot is the same content regardless of delivery mechanism — a
concise block an agent can read at startup to restore full context without
needing to recall manually.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.push.snapshot")

_MAX_MEMORIES = 8
_MAX_CONCLUSIONS = 5
_MAX_SESSIONS = 1


async def build_snapshot(db: AsyncSession, agent_id: str) -> str:
    """Build a markdown context snapshot for the given agent."""

    # Resolve agent UUID
    agent_row = (await db.execute(text("""
        SELECT id, name FROM agents WHERE name = :name LIMIT 1
    """), {"name": agent_id})).fetchone()

    if not agent_row:
        return f"# Nexus Context\nAgent `{agent_id}` not found.\n"

    aid = str(agent_row.id)

    # Top memories by importance
    memories = (await db.execute(text("""
        SELECT content, memory_type, importance, confidence, tags
        FROM memories
        WHERE agent_id = :aid
          AND superseded_by IS NULL
          AND (valid_until IS NULL OR valid_until > NOW())
        ORDER BY importance DESC, access_count DESC
        LIMIT :limit
    """), {"aid": aid, "limit": _MAX_MEMORIES})).fetchall()

    # Conclusions (distilled lessons/preferences/rules)
    conclusions = (await db.execute(text("""
        SELECT content, conclusion_type, confidence
        FROM conclusions
        WHERE agent_id = :aid
        ORDER BY confidence DESC
        LIMIT :limit
    """), {"aid": aid, "limit": _MAX_CONCLUSIONS})).fetchall()

    # Most recent session summary
    last_session = (await db.execute(text("""
        SELECT title, started_at, ended_at,
               (SELECT content FROM memories m
                WHERE m.metadata->>'source' = 'session'
                  AND m.metadata->>'session_id' = s.id::text
                LIMIT 1) AS summary
        FROM sessions s
        WHERE s.agent_name = :agent_id
          AND s.ended_at IS NOT NULL
        ORDER BY s.started_at DESC
        LIMIT 1
    """), {"agent_id": agent_id})).fetchone()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"<!-- NEXUS_CONTEXT_START -->",
        f"## Nexus Active Memory — {now}",
        f"Agent: `{agent_id}`",
        "",
    ]

    if conclusions:
        lines.append("### Preferences & Rules")
        for c in conclusions:
            tag = f"[{c.conclusion_type}] " if c.conclusion_type else ""
            lines.append(f"- {tag}{c.content}")
        lines.append("")

    if memories:
        lines.append("### Key Memories")
        for m in memories:
            tag = f"[{m.memory_type}] " if m.memory_type else ""
            lines.append(f"- {tag}{m.content}")
        lines.append("")

    if last_session:
        lines.append("### Last Session")
        ts = last_session.started_at.strftime("%Y-%m-%d") if last_session.started_at else "?"
        lines.append(f"**{last_session.title or 'Untitled'}** ({ts})")
        if last_session.summary:
            lines.append(last_session.summary)
        lines.append("")

    lines.append("<!-- NEXUS_CONTEXT_END -->")
    return "\n".join(lines)
