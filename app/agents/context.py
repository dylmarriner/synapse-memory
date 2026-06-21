"""Token-budgeted context assembly for agents — includes rolling summary."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import MemoryResult, AgentContextResponse
from app.config import settings

log = logging.getLogger("nexus.agents.context")

_CHARS_PER_TOKEN = 4


async def get_context(
    db: AsyncSession,
    agent_name: str,
    token_budget: int = 2000,
    search_query: Optional[str] = None,
) -> AgentContextResponse:
    """Assemble token-budgeted context for an agent, with rolling summary at the top."""
    budget = token_budget * _CHARS_PER_TOKEN

    agent_row = await db.execute(
        text("SELECT id, representation FROM agents WHERE name = :name"),
        {"name": agent_name},
    )
    row = agent_row.fetchone()
    if not row:
        return AgentContextResponse(agent_id=agent_name)

    agent_id = row.id
    representation = row.representation or ""
    budget -= len(representation)

    # Load latest rolling summary (most useful for session start)
    summary = None
    try:
        s_row = await db.execute(text("""
            SELECT content FROM summaries WHERE agent_id = CAST(:id AS uuid)
            ORDER BY created_at DESC LIMIT 1
        """), {"id": str(agent_id)})
        s = s_row.fetchone()
        if s:
            summary = s.content
            budget -= len(summary)
    except Exception:
        pass

    # Conclusions become explicit prompt rules so agents act on them.
    conclusion_limit = max(1, settings.context_conclusion_limit)
    c_rows = await db.execute(
        text("SELECT content FROM conclusions WHERE agent_id = CAST(:id AS uuid) ORDER BY created_at DESC LIMIT :limit"),
        {"id": str(agent_id), "limit": conclusion_limit},
    )
    conclusions = [f"REMEMBER: {r.content}" for r in c_rows.fetchall()]
    budget -= sum(len(c) for c in conclusions)

    # Unread agent-to-agent notes are injected once, then marked read in metadata.
    note_rows = await db.execute(text("""
        SELECT m.id, m.content, m.metadata, a.name AS source_agent
        FROM memories m
        LEFT JOIN agents a ON a.id = m.agent_id
        WHERE COALESCE(m.metadata->'tags', '[]'::jsonb) ? 'agent-note'
          AND (m.metadata->>'target_agent' = :agent_name OR m.metadata->>'target_agent' = :agent_id)
          AND COALESCE(m.metadata->>'read', 'false') != 'true'
        ORDER BY m.created_at ASC
        LIMIT 10
    """), {"agent_name": agent_name, "agent_id": str(agent_id)})
    unread_note_ids = []
    for note in note_rows.fetchall():
        source = note.source_agent or (note.metadata or {}).get("source_agent") or "unknown"
        msg = f"📬 Unread message from {source}: {note.content}"
        conclusions.append(msg)
        unread_note_ids.append(str(note.id))
        budget -= len(msg)
    if unread_note_ids:
        await db.execute(text("""
            UPDATE memories
            SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"read": true}'::jsonb
            WHERE id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": unread_note_ids})
        await db.commit()

    # Memories — prioritize lessons and high-importance
    memories: List[MemoryResult] = []
    if budget > 0:
        m_rows = await db.execute(
            text("""
                SELECT id, content, memory_type, importance, access_count, created_at, metadata
                FROM memories
                WHERE agent_id = CAST(:id AS uuid)
                   OR agent_id = (SELECT id FROM agents WHERE name = 'global' LIMIT 1)
                ORDER BY
                    CASE memory_type
                        WHEN 'lesson' THEN 0
                        WHEN 'preference' THEN 1
                        WHEN 'observation' THEN 2
                        WHEN 'world' THEN 3
                        WHEN 'experience' THEN 4
                        ELSE 5
                    END,
                    importance DESC,
                    created_at DESC
                LIMIT :limit
            """),
            {"id": str(agent_id), "limit": max(1, settings.context_memory_limit)},
        )
        for r in m_rows.fetchall():
            if budget <= 0:
                break
            content = r.content
            char_limit = max(80, settings.context_memory_char_limit)
            if len(content) > char_limit:
                content = content[:char_limit].rstrip() + "…"
            memories.append(MemoryResult(
                id=str(r.id),
                content=content,
                score=float(r.importance),
                memory_type=r.memory_type,
                agent_id=agent_name,
                agent_name=agent_name,
                importance=float(r.importance),
                access_count=r.access_count,
                created_at=r.created_at,
                metadata=r.metadata or {},
            ))
            budget -= len(content)

    e_row = await db.execute(
        text("SELECT COUNT(*) AS cnt FROM entities WHERE agent_id = CAST(:id AS uuid)"),
        {"id": str(agent_id)},
    )
    entity_count = e_row.scalar() or 0

    # On-demand summary rebuild (lazy — only when context is requested)
    if agent_row and len(memories) >= 5 and not summary:
        # Try to build a fresh summary
        try:
            from app.memory.extract import _build_summary, _get_llm
            llm = _get_llm()
            if llm:
                summary = await _build_summary(agent_name, str(agent_id), db, llm)
                if summary:
                    budget -= len(summary)
        except Exception:
            pass

    return AgentContextResponse(
        agent_id=agent_name,
        representation=representation or None,
        summary=summary,
        recent_memories=memories,
        conclusions=conclusions,
        entity_count=entity_count,
    )
