"""Memory ingestion — save to DB, queue background extraction, broadcast to SSE."""

import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Optional, List

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.schema import Memory, Agent
from app.models.api import MemorySaveRequest, MemorySaveResponse
from app.embeddings import get_embedding

log = logging.getLogger("nexus.memory.ingest")


async def save_memory(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    req: MemorySaveRequest,
) -> MemorySaveResponse:
    """Save a memory, attempt immediate embedding, queue LLM extraction, broadcast."""
    agent = await _ensure_agent(db, req.agent_id)

    meta = dict(req.metadata)
    if req.tags:
        meta["tags"] = req.tags

    await _update_agent_metadata_from_memory(db, agent, meta)

    # Bump importance for lesson type
    importance = req.importance
    if req.memory_type == "lesson" and importance < 0.8:
        importance = 0.9

    embedding = await get_embedding(req.content)

    agent_db_id = agent.id if agent else None
    duplicate = await _find_semantic_duplicate(db, agent_db_id, embedding, req.content)
    if duplicate:
        bumped_importance = max(float(duplicate.importance or 0.0), importance)
        await db.execute(text("""
            UPDATE memories
            SET access_count = access_count + 1,
                accessed_at = NOW(),
                importance = LEAST(1.0, :importance + 0.02),
                metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:metadata_json AS jsonb)
            WHERE id = :id
        """), {
            "id": duplicate.id,
            "importance": bumped_importance,
            "metadata_json": json.dumps({"deduped_at": datetime.now(timezone.utc).isoformat(), "latest_tags": req.tags}),
        })
        await db.commit()
        return MemorySaveResponse(
            id=str(duplicate.id),
            classified_type=duplicate.memory_type,
            extraction_queued=False,
            deduplicated=True,
        )

    memory = Memory(
        id=uuid.uuid4(),
        agent_id=agent_db_id,
        content=req.content,
        memory_type=req.memory_type or "observation",
        embedding=embedding,
        importance=importance,
        metadata_=meta,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)

    extraction_queued = False
    if redis_client:
        try:
            job = {
                "memory_id": str(memory.id),
                "agent_id": req.agent_id,
                "content": req.content,
                "importance": importance,
                "needs_embedding": embedding is None,
                "needs_classification": req.memory_type is None,
            }
            await redis_client.rpush("nexus:extract", json.dumps(job))
            extraction_queued = True
        except Exception as e:
            log.warning("Failed to queue extraction: %s", e)

    # Broadcast to SSE clients
    try:
        from app import broadcaster
        await broadcaster.broadcast("memory", {
            "id": str(memory.id),
            "content": req.content[:200],
            "memory_type": memory.memory_type,
            "agent_name": req.agent_id,
            "importance": importance,
        })
    except Exception:
        pass

    return MemorySaveResponse(
        id=str(memory.id),
        classified_type=memory.memory_type,
        extraction_queued=extraction_queued,
        deduplicated=False,
    )


async def _update_agent_metadata_from_memory(db: AsyncSession, agent: Optional[Agent], meta: dict) -> None:
    """Promote device/source hints from memory metadata onto the agent registry."""
    if not agent or not meta:
        return
    promoted = {}
    for source_key, target_key in (
        ("device", "device"),
        ("device_name", "device"),
        ("hostname", "hostname"),
        ("host", "hostname"),
        ("machine", "hostname"),
        ("source", "source"),
        ("client", "source"),
        ("model", "model"),
    ):
        value = meta.get(source_key)
        if isinstance(value, str) and value.strip():
            promoted[target_key] = value.strip()
    capabilities = meta.get("capabilities")
    if isinstance(capabilities, list):
        promoted["capabilities"] = [str(c) for c in capabilities if str(c).strip()]
    if not promoted:
        return
    try:
        await db.execute(text("""
            UPDATE agents
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb)
            WHERE id = :id
        """), {"id": agent.id, "patch": json.dumps(promoted)})
        await db.commit()
    except Exception as e:
        log.debug("Agent metadata promotion failed: %s", e)


async def _find_semantic_duplicate(
    db: AsyncSession,
    agent_id,
    embedding: Optional[List[float]],
    content: str,
    threshold: float = 0.92,
):
    """Return a near-duplicate memory row for this agent/content, if one exists."""
    if embedding:
        try:
            dims = settings.embedding_dims
            result = await db.execute(text(f"""
                SELECT id, memory_type, importance
                FROM memories
                WHERE agent_id IS NOT DISTINCT FROM :agent_id
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:emb AS vector({dims}))) >= :threshold
                ORDER BY 1 - (embedding <=> CAST(:emb AS vector({dims}))) DESC, importance DESC
                LIMIT 1
            """), {"agent_id": agent_id, "emb": str(embedding), "threshold": threshold})
            row = result.fetchone()
            if row:
                return row
        except Exception as e:
            log.debug("Semantic duplicate check failed: %s", e)

    try:
        result = await db.execute(text("""
            SELECT id, memory_type, importance
            FROM memories
            WHERE agent_id IS NOT DISTINCT FROM :agent_id
              AND LOWER(TRIM(content)) = LOWER(TRIM(:content))
            LIMIT 1
        """), {"agent_id": agent_id, "content": content})
        return result.fetchone()
    except Exception as e:
        log.debug("Exact duplicate check failed: %s", e)
        return None


async def _ensure_agent(db: AsyncSession, name: str) -> Optional[Agent]:
    try:
        result = await db.execute(text("SELECT id FROM agents WHERE name = :name"), {"name": name})
        row = result.fetchone()
        if row:
            a = Agent()
            a.id = row.id
            return a

        a = Agent(name=name, metadata_={"device": socket.gethostname(), "source": "nexus-api"})
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a
    except Exception as e:
        log.warning("Agent ensure failed for %s: %s", name, e)
        return None


async def bump_access(db: AsyncSession, memory_ids: List[str]):
    """Increment access_count + importance boost for recalled memories."""
    if not memory_ids:
        return
    try:
        await db.execute(
            text("""
                UPDATE memories
                SET access_count = access_count + 1,
                    accessed_at = NOW(),
                    importance = LEAST(1.0, importance + 0.01)
                WHERE id = ANY(CAST(:ids AS uuid[]))
            """),
            {"ids": memory_ids},
        )
        await db.commit()
    except Exception as e:
        log.debug("Access bump failed: %s", e)
