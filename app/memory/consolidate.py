"""Memory consolidation — decay, semantic deduplication, and LLM organization."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.merge import merge_memories_by_superseding
from app.memory.organize import organize_memories

log = logging.getLogger("nexus.memory.consolidate")

SIMILARITY_THRESHOLD = 0.82


async def consolidate(db: AsyncSession) -> Dict[str, int]:
    stats: Dict[str, int] = {
        "context_boosted": 0,
        "boosted": 0,
        "decayed": 0,
        "deduplicated": 0,
        "semantic_deduped": 0,
        "confidence_decayed": 0,
    }

    try:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        r = await db.execute(text("""
            UPDATE memories
            SET importance = LEAST(1.0, importance + 0.15),
                accessed_at = NOW()
            WHERE access_count >= 3
              AND accessed_at > :recent_cutoff
              AND importance < 0.95
              AND memory_type != 'lesson'
            RETURNING id
        """), {"recent_cutoff": recent_cutoff})
        stats["context_boosted"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Context boost pass failed: %s", e)

    try:
        r = await db.execute(text("""
            UPDATE memories
            SET importance = LEAST(1.0, importance * 1.05)
            WHERE access_count > 5 AND importance < 1.0
            RETURNING id
        """))
        stats["boosted"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Boost pass failed: %s", e)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        r = await db.execute(text("""
            UPDATE memories
            SET importance = GREATEST(0.05, importance * 0.9)
            WHERE accessed_at < :cutoff AND importance > 0.1 AND memory_type != 'lesson'
            RETURNING id
        """), {"cutoff": cutoff})
        stats["decayed"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Decay pass failed: %s", e)

    try:
        dup_rows = await db.execute(text("""
            WITH ranked AS (
                SELECT id,
                       FIRST_VALUE(id) OVER (
                           PARTITION BY LOWER(TRIM(content)), agent_id
                           ORDER BY importance DESC, created_at DESC
                       ) AS keep_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(TRIM(content)), agent_id
                           ORDER BY importance DESC, created_at DESC
                       ) AS rn
                FROM memories
                WHERE superseded_by IS NULL
            )
            SELECT id, keep_id
            FROM ranked
            WHERE rn > 1 AND id != keep_id
        """))
        merged = 0
        for row in dup_rows.fetchall():
            if await merge_memories_by_superseding(db, str(row.keep_id), str(row.id), source="exact-dedup", reason="exact normalized content match", confidence=1.0):
                merged += 1
        stats["deduplicated"] = merged
    except Exception as e:
        log.warning("Exact dedup pass failed: %s", e)

    try:
        dup_rows = await db.execute(text(f"""
            SELECT a.id AS keep_id, b.id AS drop_id,
                   1 - (a.embedding <=> b.embedding) AS similarity
            FROM memories a
            JOIN memories b ON b.id > a.id
                AND b.agent_id IS NOT DISTINCT FROM a.agent_id
            WHERE a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
              AND a.superseded_by IS NULL
              AND b.superseded_by IS NULL
              AND 1 - (a.embedding <=> b.embedding) > {SIMILARITY_THRESHOLD}
              AND a.memory_type != 'lesson'
              AND b.memory_type != 'lesson'
            ORDER BY similarity DESC
            LIMIT 500
        """))
        to_drop = set()
        merged = 0
        for row in dup_rows.fetchall():
            keep_id = str(row.keep_id)
            drop_id = str(row.drop_id)
            if keep_id in to_drop or drop_id in to_drop:
                continue
            if await merge_memories_by_superseding(db, keep_id, drop_id, source="semantic-dedup", reason=f"embedding similarity {float(row.similarity):.3f}", confidence=float(row.similarity or 0.9)):
                merged += 1
                to_drop.add(drop_id)
        stats["semantic_deduped"] = merged
    except Exception as e:
        log.warning("Semantic dedup pass failed: %s", e)

    try:
        r = await db.execute(text("""
            UPDATE memories
            SET confidence = GREATEST(:floor, confidence * :rate)
            WHERE created_at < NOW() - INTERVAL '1 day' * :interval_days
              AND superseded_by IS NULL
              AND confidence > :floor
            RETURNING id
        """), {
            "floor": settings.confidence_floor,
            "rate": settings.confidence_decay_rate,
            "interval_days": settings.confidence_decay_interval_days,
        })
        stats["confidence_decayed"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Confidence decay pass failed: %s", e)

    stats["pruned"] = 0
    if settings.prune_enabled:
        try:
            r = await db.execute(text("""
                DELETE FROM memories
                WHERE importance < :floor
                  AND accessed_at < NOW() - INTERVAL '1 day' * :days
                  AND memory_type NOT IN ('lesson', 'preference')
                  AND COALESCE(metadata->>'failure', 'false') != 'true'
                  AND superseded_by IS NULL
                  AND id NOT IN (SELECT superseded_by FROM memories WHERE superseded_by IS NOT NULL)
                RETURNING id
            """), {"floor": settings.prune_importance_floor, "days": settings.prune_stale_days})
            stats["pruned"] = len(r.fetchall())
            await db.commit()
        except Exception as e:
            log.warning("Prune pass failed: %s", e)

    stats["procedures_compacted"] = 0
    try:
        from app.memory.procedures import compact_project_procedures
        from app.llm import get_llm_client
        llm = get_llm_client()
        if llm:
            proj_rows = await db.execute(text("""
                SELECT DISTINCT metadata->>'project_key' AS pk
                FROM memories
                WHERE memory_type = 'procedure'
                  AND superseded_by IS NULL
                  AND COALESCE(metadata->>'compacted', 'false') != 'true'
                  AND metadata->>'project_key' IS NOT NULL
                  AND metadata->>'project_key' != ''
                GROUP BY metadata->>'project_key'
                HAVING COUNT(*) >= 5
            """))
            for prow in proj_rows.fetchall():
                result = await compact_project_procedures(db, prow.pk, llm)
                if result:
                    stats["procedures_compacted"] += 1
    except Exception as e:
        log.warning("Procedure compaction pass failed: %s", e)

    try:
        stats.update(await organize_memories(db))
    except Exception as e:
        log.warning("LLM organizer pass failed: %s", e)

    log.info("Consolidation: %s", stats)
    return stats


async def detect_and_update_contradictions(db: AsyncSession, new_content: str, agent_id_str: Optional[str], new_memory_id: str):
    negation_pairs = [
        ("prefers", "does not prefer"), ("likes", "dislikes"),
        ("always", "never"), ("can", "cannot"), ("is", "is not"),
    ]
    try:
        lowered = new_content.lower()
        for pos, neg in negation_pairs:
            if pos in lowered or neg in lowered:
                opposite = neg if pos in lowered else pos
                result = await db.execute(text("""
                    SELECT id FROM memories
                    WHERE agent_id = (SELECT id FROM agents WHERE name = :name LIMIT 1)
                      AND LOWER(content) LIKE :pattern
                      AND id != CAST(:new_id AS uuid)
                    LIMIT 5
                """), {"name": agent_id_str or "", "pattern": f"%{opposite}%", "new_id": new_memory_id})
                ids = [str(r.id) for r in result.fetchall()]
                for mid in ids:
                    await db.execute(text("UPDATE memories SET contradicted_count = contradicted_count + 1 WHERE id = CAST(:id AS uuid)"), {"id": mid})
        await db.commit()
    except Exception as e:
        log.debug("Contradiction detection failed: %s", e)
