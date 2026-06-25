"""Memory consolidation — decay, semantic deduplication, importance boosting."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger("nexus.memory.consolidate")

SIMILARITY_THRESHOLD = 0.82


async def consolidate(db: AsyncSession) -> Dict[str, int]:
    """
    Six-pass consolidation:
    1. Smart importance auto-scaling - boost memories recalled multiple times in conversation
    2. Boost importance of frequently accessed memories
    3. Decay importance of memories not accessed in 30+ days
    4. Remove exact content duplicates (keep newest per agent)
    5. Semantic deduplication via embedding cosine similarity
    6. Confidence decay — weekly decay for aging memories
    """
    stats: Dict[str, int] = {"context_boosted": 0, "boosted": 0, "decayed": 0, "deduplicated": 0, "semantic_deduped": 0, "confidence_decayed": 0}

    # Pass 1: Smart importance auto-scaling - boost memories recalled frequently in recent context
    try:
        # If a memory was accessed 3+ times in the last hour, it's part of active conversation
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
        if stats["context_boosted"] > 0:
            log.info("Smart importance scaling: boosted %d active conversation memories", stats["context_boosted"])
    except Exception as e:
        log.warning("Context boost pass failed: %s", e)

    # Pass 2: Boost memories accessed frequently (access_count > 5)
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

    # Pass 3: Decay stale memories
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        r = await db.execute(
            text("""
                UPDATE memories
                SET importance = GREATEST(0.05, importance * 0.9)
                WHERE accessed_at < :cutoff AND importance > 0.1 AND memory_type != 'lesson'
                RETURNING id
            """),
            {"cutoff": cutoff},
        )
        stats["decayed"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Decay pass failed: %s", e)

    # Pass 4: Exact content deduplication
    try:
        r = await db.execute(text("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(TRIM(content)), agent_id
                           ORDER BY importance DESC, created_at DESC
                       ) AS rn
                FROM memories
            )
            DELETE FROM memories
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            RETURNING id
        """))
        stats["deduplicated"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Exact dedup pass failed: %s", e)

    # Pass 5: Semantic deduplication — find near-duplicate embeddings
    try:
        # Find pairs of memories with very high cosine similarity
        dup_rows = await db.execute(text(f"""
            SELECT a.id AS keep_id, b.id AS drop_id,
                   1 - (a.embedding <=> b.embedding) AS similarity
            FROM memories a
            JOIN memories b ON b.id > a.id
                AND b.agent_id IS NOT DISTINCT FROM a.agent_id
            WHERE a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
              AND 1 - (a.embedding <=> b.embedding) > {SIMILARITY_THRESHOLD}
              AND a.memory_type != 'lesson'
              AND b.memory_type != 'lesson'
            ORDER BY similarity DESC
            LIMIT 500
        """))
        pairs = dup_rows.fetchall()

        to_drop = set()
        for row in pairs:
            keep = str(row.keep_id)
            drop = str(row.drop_id)
            # Don't drop something we're keeping, avoid cascade conflicts
            if drop not in to_drop and keep not in to_drop:
                to_drop.add(drop)

        if to_drop:
            for drop_id in to_drop:
                await db.execute(
                    text("DELETE FROM memories WHERE id = CAST(:id AS uuid)"),
                    {"id": drop_id},
                )
            await db.commit()
            stats["semantic_deduped"] = len(to_drop)
    except Exception as e:
        log.warning("Semantic dedup pass failed: %s", e)

    # Pass 6: Confidence decay — weekly decay for memories older than interval_days
    try:
        r = await db.execute(
            text("""
                UPDATE memories
                SET confidence = GREATEST(:floor, confidence * :rate)
                WHERE created_at < NOW() - INTERVAL '1 day' * :interval_days
                  AND superseded_by IS NULL
                  AND confidence > :floor
                RETURNING id
            """),
            {
                "floor": settings.confidence_floor,
                "rate": settings.confidence_decay_rate,
                "interval_days": settings.confidence_decay_interval_days,
            },
        )
        stats["confidence_decayed"] = len(r.fetchall())
        await db.commit()
    except Exception as e:
        log.warning("Confidence decay pass failed: %s", e)

    log.info("Consolidation: %s", stats)
    return stats


async def detect_and_update_contradictions(
    db: AsyncSession,
    new_content: str,
    agent_id_str: Optional[str],
    new_memory_id: str,
):
    """
    Simple contradiction detection: if new memory has opposite signal words
    to an existing memory about the same subject, mark the old one.
    """
    NEGATION_PAIRS = [
        ("prefers", "does not prefer"), ("likes", "dislikes"),
        ("always", "never"), ("can", "cannot"), ("is", "is not"),
    ]
    try:
        for pos, neg in NEGATION_PAIRS:
            if pos in new_content.lower() or neg in new_content.lower():
                # Check for existing memories with the opposite signal
                opposite = neg if pos in new_content.lower() else pos
                result = await db.execute(
                    text("""
                        SELECT id FROM memories
                        WHERE agent_id = (SELECT id FROM agents WHERE name = :name LIMIT 1)
                          AND LOWER(content) LIKE :pattern
                          AND id != CAST(:new_id AS uuid)
                        LIMIT 5
                    """),
                    {"name": agent_id_str or "", "pattern": f"%{opposite}%", "new_id": new_memory_id},
                )
                ids = [str(r.id) for r in result.fetchall()]
                for mid in ids:
                    await db.execute(
                        text("UPDATE memories SET contradicted_count = contradicted_count + 1 WHERE id = CAST(:id AS uuid)"),
                        {"id": mid},
                    )
        await db.commit()
    except Exception as e:
        log.debug("Contradiction detection failed: %s", e)
