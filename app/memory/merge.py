"""Memory merge helpers that preserve old rows by superseding them.

Merging never hard-deletes source memories. The survivor absorbs trust and
usage, the older row is marked `superseded_by`, and a `supersedes` link is
written into the memory graph.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.layers import link_memories

log = logging.getLogger("nexus.memory.merge")


async def merge_memories_by_superseding(
    db: AsyncSession,
    keep_id: str,
    drop_id: str,
    *,
    source: str,
    reason: Optional[str] = None,
    confidence: float = 1.0,
) -> bool:
    """Merge `drop_id` into `keep_id` without deleting `drop_id`."""
    if not keep_id or not drop_id or keep_id == drop_id:
        return False

    keep_meta = {
        "last_merge_source": source,
        "last_merge_reason": reason or "",
    }
    drop_meta = {
        "merged_into": keep_id,
        "merged_by": source,
        "merge_reason": reason or "",
    }

    await db.execute(text("""
        UPDATE memories keep
        SET access_count = keep.access_count + drop.access_count,
            confirmed_count = keep.confirmed_count + drop.confirmed_count + 1,
            contradicted_count = keep.contradicted_count + drop.contradicted_count,
            importance = LEAST(1.0, GREATEST(keep.importance, drop.importance)),
            confidence = GREATEST(keep.confidence, drop.confidence),
            metadata = COALESCE(keep.metadata, '{}'::jsonb) || CAST(:keep_meta AS jsonb)
        FROM memories drop
        WHERE keep.id = CAST(:keep AS uuid)
          AND drop.id = CAST(:drop AS uuid)
          AND keep.superseded_by IS NULL
    """), {
        "keep": keep_id,
        "drop": drop_id,
        "keep_meta": json.dumps(keep_meta),
    })

    result = await db.execute(text("""
        UPDATE memories
        SET superseded_by = CAST(:keep AS uuid),
            valid_until = COALESCE(valid_until, NOW()),
            metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:drop_meta AS jsonb)
        WHERE id = CAST(:drop AS uuid)
          AND superseded_by IS NULL
        RETURNING id
    """), {
        "keep": keep_id,
        "drop": drop_id,
        "drop_meta": json.dumps(drop_meta),
    })
    row = result.fetchone()
    if not row:
        return False

    await db.commit()

    try:
        await link_memories(
            db,
            keep_id,
            drop_id,
            kind="supersedes",
            weight=max(0.0, min(1.0, confidence)),
            metadata={"source": source, "reason": reason or ""},
        )
    except Exception as e:
        log.debug("failed to write supersedes link %s -> %s: %s", keep_id, drop_id, e)

    return True
