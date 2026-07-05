"""Living self-model and user-model — evolving identity documents stored in agent metadata."""

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

log = logging.getLogger("nexus.agents.selfmodel")

_SELF_MODEL_PROMPT = """You maintain a living self-model for an AI agent. Revise it based on a new episode.

CURRENT SELF-MODEL:
{current}

NEW EPISODE:
{episode}

Rules: keep "core" stable unless something fundamental changed; update "recent_growth" to reflect what was learned; refine "known_weaknesses" only if confirmed; keep "working_style" accurate. Be terse — each field max 2 sentences.

Return ONLY valid JSON with keys: core, working_style, known_weaknesses, recent_growth"""

_USER_MODEL_PROMPT = """You maintain a living model of the user this agent works with. Revise it based on a new episode.

CURRENT USER MODEL:
{current}

NEW EPISODE:
{episode}

Rules: update only fields that the episode provides evidence for; be specific not generic; keep "frustrations" honest. Each field max 2 sentences.

Return ONLY valid JSON with keys: expertise, communication_style, values, current_focus, frustrations"""

_DEFAULT_SELF_MODEL = {
    "core": "An AI coding agent focused on building software and solving problems.",
    "working_style": "Reads code before writing. Prefers targeted edits over rewrites.",
    "known_weaknesses": "May over-explain. Can miss context not visible in the current session.",
    "recent_growth": "",
    "version": 0,
}

_DEFAULT_USER_MODEL = {
    "expertise": "Unknown — learning from interactions.",
    "communication_style": "Unknown.",
    "values": "Unknown.",
    "current_focus": "Unknown.",
    "frustrations": "Unknown.",
    "version": 0,
}


async def _get_agent_metadata(db: AsyncSession, agent_name: str) -> dict:
    row = (await db.execute(
        text("SELECT metadata FROM agents WHERE name = :name LIMIT 1"),
        {"name": agent_name},
    )).fetchone()
    if not row or not row.metadata:
        return {}
    return dict(row.metadata)


async def _patch_agent_metadata(db: AsyncSession, agent_name: str, patch: dict) -> None:
    await db.execute(text("""
        UPDATE agents
        SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb)
        WHERE name = :name
    """), {"name": agent_name, "patch": json.dumps(patch)})
    await db.commit()


async def get_self_model(db: AsyncSession, agent_name: str) -> dict:
    meta = await _get_agent_metadata(db, agent_name)
    return dict(meta.get("self_model") or _DEFAULT_SELF_MODEL)


async def get_user_model(db: AsyncSession, agent_name: str) -> dict:
    meta = await _get_agent_metadata(db, agent_name)
    return dict(meta.get("user_model") or _DEFAULT_USER_MODEL)


async def update_self_model(db: AsyncSession, agent_name: str, llm, episode_summary: str) -> Optional[dict]:
    current = await get_self_model(db, agent_name)
    prompt = _SELF_MODEL_PROMPT.format(
        current=json.dumps(current, indent=None)[:600],
        episode=episode_summary[:300],
    )
    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        updated = json.loads(raw)
        updated["version"] = current.get("version", 0) + 1
        await _patch_agent_metadata(db, agent_name, {"self_model": updated})
        log.info("Self-model updated for %s (v%d)", agent_name, updated["version"])
        return updated
    except Exception as e:
        log.debug("update_self_model failed: %s", e)
        return None


async def update_user_model(db: AsyncSession, agent_name: str, llm, episode_summary: str) -> Optional[dict]:
    current = await get_user_model(db, agent_name)
    prompt = _USER_MODEL_PROMPT.format(
        current=json.dumps(current, indent=None)[:600],
        episode=episode_summary[:300],
    )
    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        updated = json.loads(raw)
        updated["version"] = current.get("version", 0) + 1
        await _patch_agent_metadata(db, agent_name, {"user_model": updated})
        log.info("User-model updated for %s (v%d)", agent_name, updated["version"])
        return updated
    except Exception as e:
        log.debug("update_user_model failed: %s", e)
        return None
