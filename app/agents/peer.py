"""Agent peer management — identity, LLM representation, rolling summaries."""

import logging
import socket
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger("nexus.agents.peer")

_REPRESENT_PROMPT = """Build a concise, dense representation of this agent based on what is known about them.

Agent: {name}

Conclusions:
{conclusions}

Recent important memories:
{memories}

Write 3-5 sentences: who they are, what they know, their preferences, and their behavioral patterns.
Be specific — avoid vague generalities."""


async def get_or_create(db: AsyncSession, name: str) -> dict:
    """Return agent dict (id, name, representation), creating if necessary."""
    result = await db.execute(
        text("SELECT id, name, representation FROM agents WHERE name = :name"),
        {"name": name},
    )
    row = result.fetchone()
    if row:
        return {"id": str(row.id), "name": row.name, "representation": row.representation}

    await db.execute(
        text("""
            INSERT INTO agents (name, metadata)
            VALUES (:name, CAST(:metadata AS jsonb))
            ON CONFLICT (name) DO NOTHING
        """),
        {"name": name, "metadata": '{"device": "' + socket.gethostname() + '", "source": "nexus-api"}'},
    )
    await db.commit()

    result2 = await db.execute(
        text("SELECT id, name FROM agents WHERE name = :name"), {"name": name}
    )
    row2 = result2.fetchone()
    return {"id": str(row2.id), "name": row2.name, "representation": None}


async def ensure_global_agent(db: AsyncSession):
    """Ensure the 'global' shared memory agent exists."""
    await db.execute(text("""
        INSERT INTO agents (name, metadata)
        VALUES ('global', '{"system": true, "description": "Shared global memory pool — accessible by all agents"}')
        ON CONFLICT (name) DO NOTHING
    """))
    await db.commit()


async def build_representation(db: AsyncSession, agent_name: str) -> Optional[str]:
    """Generate and store an LLM representation of an agent."""
    from app.llm import get_llm_client
    client = get_llm_client()
    if client is None:
        return None

    try:
        c_rows = await db.execute(text("""
            SELECT c.content FROM conclusions c
            JOIN agents a ON c.agent_id = a.id
            WHERE a.name = :name
            ORDER BY c.created_at DESC LIMIT 20
        """), {"name": agent_name})
        conclusions = [r.content for r in c_rows.fetchall()]

        m_rows = await db.execute(text("""
            SELECT m.content, m.memory_type FROM memories m
            JOIN agents a ON m.agent_id = a.id
            WHERE a.name = :name
            ORDER BY m.importance DESC, m.access_count DESC, m.created_at DESC LIMIT 15
        """), {"name": agent_name})
        memories = [f"[{r.memory_type}] {r.content}" for r in m_rows.fetchall()]

        if not conclusions and not memories:
            return None

        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _REPRESENT_PROMPT.format(
                name=agent_name,
                conclusions="\n".join(f"- {c}" for c in conclusions) or "(none yet)",
                memories="\n".join(f"- {m}" for m in memories) or "(none yet)",
            )}],
            max_tokens=250,
            temperature=0.2,
        )
        representation = resp.choices[0].message.content.strip()

        await db.execute(
            text("UPDATE agents SET representation = :rep, represented_at = NOW() WHERE name = :name"),
            {"rep": representation, "name": agent_name},
        )
        await db.commit()
        return representation
    except Exception as e:
        log.warning("Representation build failed for %s: %s", agent_name, e)
        return None


async def get_latest_summary(db: AsyncSession, agent_name: str) -> Optional[str]:
    """Get the most recent rolling summary for an agent."""
    try:
        row = await db.execute(text("""
            SELECT s.content FROM summaries s
            JOIN agents a ON s.agent_id = a.id
            WHERE a.name = :name
            ORDER BY s.created_at DESC
            LIMIT 1
        """), {"name": agent_name})
        result = row.fetchone()
        return result.content if result else None
    except Exception:
        return None
