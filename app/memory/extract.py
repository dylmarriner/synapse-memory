"""Background worker — classifies types, extracts entities, builds summaries, detects patterns."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import redis.asyncio as aioredis
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.embeddings import get_embedding

log = logging.getLogger("nexus.memory.extract")
_WORKER_HEARTBEAT = Path("/tmp/nexus-worker-heartbeat")

_EXTRACT_PROMPT = """Return minified JSON for memory analysis:
{{
  "type": "world|experience|observation|preference|lesson",
  "entities": [{{"name": "...", "type": "person|place|organization|concept|technology|project|other"}}],
  "conclusion": "<=15 words; omit unless observation/lesson"
}}

Memory: {content}
Only JSON."""

_PATTERN_PROMPT = """Analyze these memories and identify any significant patterns or recurring themes.
Return 2-4 pattern observations as a JSON array of strings.

Memories:
{memories}

Return: ["Pattern 1...", "Pattern 2..."]"""

_SUMMARY_PROMPT = """Summarize the key knowledge, preferences, and context of this agent based on their memories.
Be specific and concise — this summary is loaded at the start of every session.

Agent: {agent_name}
Memory count: {count}

Most important memories:
{memories}

Conclusions:
{conclusions}

Write a dense, useful summary (150-250 words)."""


def _touch_worker_heartbeat() -> None:
    try:
        _WORKER_HEARTBEAT.write_text("ok")
    except Exception:
        pass


def _get_llm():
    from app.llm import get_llm_client
    return get_llm_client()
async def _batch_extract(content: str, llm, importance: float = 0.5) -> Dict[str, Any]:
    """Single LLM call for classification + entity extraction + conclusion."""
    model = settings.llm_model

    # Low-importance memories: classify only, skip entities/conclusion
    if importance < 0.4:
        try:
            resp = await llm.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Classify as world|experience|observation|preference|lesson. One word.\n" + content[:settings.llm_input_char_limit]}],
                max_tokens=10,
                temperature=0,
                timeout=10,
            )
            t = (resp.choices[0].message.content or "").strip().lower().split()[0]
            return {
                "memory_type": t if t in ("world", "experience", "observation", "preference", "lesson") else "observation",
                "entities": [],
                "conclusion": None,
            }
        except Exception as e:
            log.debug("Fast classify failed: %s", e)
            return {"memory_type": "observation", "entities": [], "conclusion": None}

    # Full batch extraction for important memories
    try:
        resp = await llm.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(content=content[:settings.llm_input_char_limit])}],
            max_tokens=settings.llm_extract_max_tokens,
            temperature=0,
            timeout=15,
        )
        raw = (resp.choices[0].message.content or "").strip()
        log.debug("Batch extract raw response: %s", raw[:200])
        # Clean response — remove markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        t = parsed.get("type", "observation")
        return {
            "memory_type": t if t in ("world", "experience", "observation", "preference", "lesson") else "observation",
            "entities": parsed.get("entities", []) if isinstance(parsed.get("entities"), list) else [],
            "conclusion": parsed.get("conclusion") if isinstance(parsed.get("conclusion"), str) else None,
        }
    except json.JSONDecodeError as e:
        log.warning("Batch extract JSON parse failed: %s. Raw: %s", e, raw[:300])
        return {"memory_type": "observation", "entities": [], "conclusion": None}
    except Exception as e:
        log.warning("Batch extract failed: %s", e)
        return {"memory_type": "observation", "entities": [], "conclusion": None}


async def _detect_patterns(memories: List[str], llm) -> List[str]:
    if len(memories) < 5:
        return []
    try:
        mem_text = "\n".join(f"- {m[:160]}" for m in memories[:12])
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _PATTERN_PROMPT.format(memories=mem_text)}],
            max_tokens=160,
            temperature=0.3,
        )
        parsed = json.loads(resp.choices[0].message.content.strip())
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


async def _build_summary(agent_name: str, agent_id: str, db, llm) -> Optional[str]:
    """Build a rolling summary for an agent and store it."""
    try:
        # Get memory count
        count_row = await db.execute(
            text("SELECT COUNT(*) FROM memories WHERE agent_id = CAST(:id AS uuid)"), {"id": agent_id}
        )
        count = count_row.scalar() or 0
        if count < 5:
            return None

        # Get top memories by importance
        m_rows = await db.execute(text("""
            SELECT content, memory_type FROM memories
            WHERE agent_id = CAST(:id AS uuid)
            ORDER BY importance DESC, created_at DESC
            LIMIT 12
        """), {"id": agent_id})
        memories = [f"[{r.memory_type}] {r.content[:settings.llm_input_char_limit // 3]}" for r in m_rows.fetchall()]

        # Get conclusions
        c_rows = await db.execute(text("""
            SELECT content FROM conclusions
            WHERE agent_id = CAST(:id AS uuid)
            ORDER BY created_at DESC LIMIT 6
        """), {"id": agent_id})
        conclusions = [r.content for r in c_rows.fetchall()]

        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _SUMMARY_PROMPT.format(
                agent_name=agent_name,
                count=count,
                memories="\n".join(f"- {m}" for m in memories),
                conclusions="\n".join(f"- {c}" for c in conclusions) or "(none yet)",
            )}],
            max_tokens=settings.llm_summary_max_tokens,
            temperature=0.2,
        )
        summary = resp.choices[0].message.content.strip()

        # Store summary
        await db.execute(text("""
            INSERT INTO summaries (agent_id, content, memory_count)
            VALUES (CAST(:agent_id AS uuid), :content, :count)
        """), {"agent_id": agent_id, "content": summary, "count": count})
        await db.commit()

        log.info("Built summary for agent %s (%d memories)", agent_name, count)
        return summary
    except Exception as e:
        log.warning("Summary build failed for %s: %s", agent_name, e)
        return None


async def _process_job(job: Dict[str, Any], llm, processed_count: list):
    memory_id = job.get("memory_id", "unknown")
    log.info("Processing job: memory_id=%s", memory_id[:12] if memory_id != "unknown" else "unknown")
    content = job["content"]
    agent_id_name = job.get("agent_id")

    updates: Dict[str, Any] = {}

    if job.get("needs_embedding"):
        emb = await get_embedding(content)
        if emb:
            updates["embedding"] = str(emb)

    memory_type = "observation"
    importance = job.get("importance", 0.5)

    if job.get("needs_classification") and llm:
        log.debug("Running batch extraction for %s", memory_id[:12])
        result = await _batch_extract(content, llm, importance)
        memory_type = result["memory_type"]
        log.debug("Batch extraction result: type=%s, entities=%d, conclusion=%s", 
                   memory_type, len(result.get("entities", [])), bool(result.get("conclusion")))
        updates["memory_type"] = memory_type

    async with SessionLocal() as db:
        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            await db.execute(
                text(f"UPDATE memories SET {set_clause} WHERE id = CAST(:id AS uuid)"),
                {"id": memory_id, **updates},
            )
            await db.commit()

        if llm and agent_id_name:
            agent_row = await db.execute(
                text("SELECT id FROM agents WHERE name = :name"), {"name": agent_id_name}
            )
            agent = agent_row.fetchone()
            agent_uuid = str(agent.id) if agent else None

            # Batch extract already ran — use results
            if job.get("needs_classification") and llm:
                entities = result["entities"]
                conclusion = result["conclusion"] if memory_type in ("observation", "lesson") else None
            else:
                entities = []
                conclusion = None

            # Store entities
            for ent in entities[:10]:
                name = (ent.get("name") or "").strip()
                etype = ent.get("type", "other")
                if not name or not agent_uuid:
                    continue
                try:
                    await db.execute(text("""
                        INSERT INTO entities (name, entity_type, agent_id)
                        VALUES (:name, :etype, CAST(:aid AS uuid))
                        ON CONFLICT (name, agent_id) DO NOTHING
                    """), {"name": name, "etype": etype, "aid": agent_uuid})
                except Exception:
                    pass
            if agent_uuid:
                await db.commit()

            # Store conclusion
            if conclusion and agent_uuid:
                await db.execute(text("""
                    INSERT INTO conclusions (agent_id, content, conclusion_type)
                    VALUES (CAST(:aid AS uuid), :content, :ctype)
                """), {"aid": agent_uuid, "content": conclusion, "ctype": memory_type})
                await db.commit()

            # Contradiction detection for important memories
            if importance >= 0.5 and llm:
                try:
                    from app.memory.contradict import detect_contradictions
                    c_stats = await detect_contradictions(db, memory_id, content, agent_id_name)
                    if c_stats["contradicted"]:
                        log.info("Memory %s contradicted %d existing memories", memory_id[:8], c_stats["contradicted"])
                except Exception as e:
                    log.debug("Contradiction detection failed: %s", e)

            # Auto-represent: check if 10+ new memories since last representation
            if agent_uuid:
                rep_row = await db.execute(text("""
                    SELECT a.represented_at, COUNT(m.id) AS new_count
                    FROM agents a
                    LEFT JOIN memories m ON m.agent_id = a.id
                        AND (a.represented_at IS NULL OR m.created_at > a.represented_at)
                    WHERE a.id = CAST(:id AS uuid)
                    GROUP BY a.represented_at
                """), {"id": agent_uuid})
                rep = rep_row.fetchone()
                if rep and (rep.new_count or 0) >= 10:
                    from app.agents.peer import build_representation
                    await build_representation(db, agent_id_name)

    # Track processed count for logging
    processed_count[0] += 1

    log.debug("Processed %s: type=%s", memory_id[:8], updates.get("memory_type", "unchanged"))


async def run_worker():
    """Blocking extraction + consolidation worker loop."""
    log.info("Nexus worker starting")
    llm = _get_llm()
    if llm:
        log.info("LLM enabled: %s", settings.llm_model)
    else:
        log.info("No LLM key — running embedding-only mode")

    redis_client = aioredis.from_url(settings.redis_url)
    processed_count = [0]
    loop_count = [0]

    # Test Redis connectivity
    try:
        import asyncio
        await redis_client.ping()
        _touch_worker_heartbeat()
        log.info("Redis connection OK")
    except Exception as e:
        log.warning("Redis ping failed: %s", e)

    while True:
        loop_count[0] += 1
        try:
            _touch_worker_heartbeat()
            # BLPOP with timeout — catches aioredis timeout quirks gracefully
            try:
                item = await redis_client.blpop(["nexus:extract", "nexus:consolidate"], timeout=5)
            except asyncio.TimeoutError:
                continue
            except ConnectionError as e:
                log.warning("Redis connection error: %s — retrying in 5s", e)
                await asyncio.sleep(5)
                continue
            except OSError as e:
                log.warning("Redis socket error: %s — retrying in 5s", e)
                await asyncio.sleep(5)
                continue
            except Exception as e:
                # Catch redis.TimeoutError and similar — harmless, just means no data yet
                ename = type(e).__name__
                if "timeout" in str(e).lower() or "Timeout" in ename:
                    continue
                raise

            if item is None:
                if loop_count[0] % 12 == 0:
                    log.debug("Worker heartbeat (loop %d)", loop_count[0])
                continue

            queue, data = item
            if queue == b"nexus:consolidate":
                async with SessionLocal() as db:
                    stats = await consolidate(db)
                    log.info("Consolidation: %s", stats)
            else:
                job = json.loads(data)
                await _process_job(job, llm, processed_count)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Worker error: %s", e)
            await asyncio.sleep(1)

    await redis_client.aclose()
    log.info("Worker stopped")


# Import here to avoid circular imports
from app.memory.consolidate import consolidate
