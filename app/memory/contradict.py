"""LLM-powered contradiction detection and resolution."""

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import get_llm_client

log = logging.getLogger("nexus.memory.contradict")

_CONTRADICT_PROMPT = """Given a NEW memory and an EXISTING memory, determine if they contradict each other.

NEW: {new_content}
EXISTING: {old_content}

Return ONLY valid JSON:
{{"contradicts": true/false, "reason": "brief explanation"}}

Rules:
- "contradicts" means they make opposing claims about the SAME subject
- Updates or corrections ARE contradictions (the old fact is no longer true)
- Different topics are NOT contradictions even if they seem opposite
- Preferences that changed ARE contradictions

Return ONLY valid JSON."""


async def detect_contradictions(
    db: AsyncSession,
    new_memory_id: str,
    new_content: str,
    agent_id: Optional[str],
) -> dict:
    """Find and handle memories that contradict the new one.

    Returns {"contradicted": count, "superseded": [ids]}
    """
    from app.embeddings import get_embedding

    stats = {"contradicted": 0, "superseded": []}

    embedding = await get_embedding(new_content)
    if not embedding:
        return stats

    dims = settings.embedding_dims
    result = await db.execute(text(f"""
        SELECT id, content, importance, memory_type,
               1 - (embedding <=> CAST(:emb AS vector({dims}))) AS similarity
        FROM memories
        WHERE embedding IS NOT NULL
          AND id != CAST(:new_id AS uuid)
          AND agent_id IS NOT DISTINCT FROM (SELECT id FROM agents WHERE name = :agent LIMIT 1)
          AND 1 - (embedding <=> CAST(:emb AS vector({dims}))) > 0.7
        ORDER BY similarity DESC
        LIMIT 5
    """), {"emb": str(embedding), "new_id": new_memory_id, "agent": agent_id or ""})
    candidates = result.fetchall()

    if not candidates:
        return stats

    llm = get_llm_client()
    if not llm:
        return stats

    for candidate in candidates:
        try:
            resp = await llm.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": _CONTRADICT_PROMPT.format(
                    new_content=new_content[:350], old_content=candidate.content[:350]
                )}],
                max_tokens=80,
                temperature=0,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)

            if parsed.get("contradicts"):
                old_id = str(candidate.id)
                await db.execute(text("""
                    UPDATE memories
                    SET contradicted_count = contradicted_count + 1,
                        superseded_by = CAST(:new_id AS uuid),
                        importance = GREATEST(0.05, importance * 0.5)
                    WHERE id = CAST(:old_id AS uuid)
                """), {"new_id": new_memory_id, "old_id": old_id})

                await db.execute(text("""
                    UPDATE memories
                    SET confirmed_count = confirmed_count + 1,
                        importance = LEAST(1.0, importance + 0.05)
                    WHERE id = CAST(:new_id AS uuid)
                """), {"new_id": new_memory_id})

                stats["contradicted"] += 1
                stats["superseded"].append(old_id)
                log.info("Contradiction: %s supersedes %s — %s",
                         new_memory_id[:8], old_id[:8], parsed.get("reason", ""))
        except Exception as e:
            log.debug("Contradiction check failed for %s: %s", str(candidate.id)[:8], e)

    if stats["contradicted"]:
        await db.commit()

    return stats
