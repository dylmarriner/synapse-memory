"""Splits oversized, multi-fact memories into smaller atomic ones via the local LLM.

The Living Mind is responsible for keeping memory organized, not just merging
duplicates — a single memory bundling several distinct facts (a multi-phase
project log, a "full context" dump, a list of unrelated notes) hurts recall
because retrieval scores the whole blob against a query instead of the one
fact that actually matches. This pass asks the LLM to decompose such memories
into self-contained facts and inserts them as new rows, leaving the original
in place (marked `decomposed`) for audit history.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.embeddings import get_embedding

log = logging.getLogger("nexus.memory.decompose")

DECOMPOSE_PROMPT = """The text below is one stored memory. Decide if it bundles multiple
distinct facts (e.g. a multi-phase project log, a "full context" summary, a list of
unrelated notes) that would each be more useful as their own memory.

If it is already a single coherent fact, return {{"facts": []}}.
Otherwise split it into self-contained facts — each must be understandable on its own,
without the others, and should not lose specifics (names, numbers, paths).

Memory:
\"\"\"{content}\"\"\"

Return strict JSON only: {{"facts": ["fact one", "fact two", ...]}}"""


async def decompose_large_memories(db: AsyncSession) -> Dict[str, int]:
    stats = {"decompose_candidates": 0, "decompose_split": 0, "decompose_facts_created": 0}
    if not settings.llm_memory_decompose_enabled:
        return stats

    from app.llm import get_llm_client
    llm = get_llm_client()
    if llm is None:
        return stats

    threshold = settings.llm_memory_decompose_length_threshold
    limit = settings.llm_memory_decompose_batch_limit
    rows = (await db.execute(text("""
        SELECT id, agent_id, content, memory_type, importance, source, source_device,
               confidence, source_type
        FROM memories
        WHERE length(content) > :threshold
          AND superseded_by IS NULL
          AND (metadata->>'decompose_checked') IS NULL
        ORDER BY length(content) DESC
        LIMIT :limit
    """), {"threshold": threshold, "limit": limit})).mappings().all()

    stats["decompose_candidates"] = len(rows)

    for row in rows:
        facts = await _split_via_llm(row["content"], llm)

        await db.execute(text("""
            UPDATE memories
            SET metadata = metadata || '{"decompose_checked": true}'::jsonb
            WHERE id = :id
        """), {"id": row["id"]})

        if len(facts) < 2:
            continue

        for fact in facts:
            emb = await get_embedding(fact)
            vec = "[" + ",".join(str(x) for x in emb) + "]" if emb else None
            await db.execute(text("""
                INSERT INTO memories
                    (agent_id, content, memory_type, importance, source, source_device,
                     confidence, source_type, embedding, metadata)
                VALUES
                    (:agent_id, :content, :memory_type, :importance, :source, :source_device,
                     :confidence, :source_type, CAST(:embedding AS vector),
                     jsonb_build_object('decomposed_from', CAST(:orig_id AS text), 'decompose_checked', true))
            """), {
                "agent_id": row["agent_id"], "content": fact, "memory_type": row["memory_type"],
                "importance": row["importance"], "source": row["source"],
                "source_device": row["source_device"], "confidence": row["confidence"],
                "source_type": row["source_type"], "embedding": vec, "orig_id": str(row["id"]),
            })
            stats["decompose_facts_created"] += 1

        await db.execute(text("""
            UPDATE memories
            SET metadata = metadata || '{"decomposed": true}'::jsonb,
                importance = LEAST(importance, 0.3)
            WHERE id = :id
        """), {"id": row["id"]})
        stats["decompose_split"] += 1
        log.info("Decomposed memory %s into %d atomic facts", row["id"], len(facts))

    await db.commit()
    return stats


async def _split_via_llm(content: str, llm) -> List[str]:
    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": DECOMPOSE_PROMPT.format(
                content=content[:settings.llm_input_char_limit])}],
            max_tokens=settings.llm_synthesis_max_tokens,
            temperature=0,
            timeout=20,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        facts = data.get("facts") or []
        return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
    except Exception as e:
        log.debug("Decompose LLM call failed: %s", e)
        return []
