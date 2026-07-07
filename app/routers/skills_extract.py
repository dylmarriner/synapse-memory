"""Skill extraction — detects and extracts reusable skills from conversations.

Scanning conversation patterns to identify:
- Sequences the agent consistently follows
- Configurations / tool invocations that form a workflow
- Solutions to recurring problems

Results are stored in the skills table and exposed as SKILL.md format content.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

log = logging.getLogger("nexus.routers.skills")
router = APIRouter()

SKILL_EXTRACT_PROMPT = """Analyze the following conversation and identify any reusable skills, workflows, or patterns.

A skill is a repeatable procedure that an agent can follow to accomplish a specific task.
Look for:
- Repeated sequences of steps
- Specific tool configurations or commands
- Problem-solution patterns
- Domain-specific workflows

For each skill found, extract:
1. name: short descriptive name
2. trigger: when to use this skill
3. steps: numbered procedure
4. tags: relevant keywords
5. importance: 0.0-1.0

Conversation:
{conversation}

Return a JSON array of skills. Return [] if none found.
Format: [{{"name": "...", "trigger": "...", "steps": "...", "tags": [...], "importance": 0.0}}]
"""


# ── CRUD Routes ─────────────────────────────────────────────────────────────

@router.post("/skills/extract")
async def extract_skills(
    agent_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    body: dict = None,
):
    """Extract skills from a conversation using LLM analysis."""
    conversation = body.get("conversation", "") if body else ""
    if not conversation.strip():
        raise HTTPException(400, "conversation is required in request body")
    client = _get_llm()
    if not client:
        # Fallback: basic pattern detection
        return await _basic_extract(db, agent_id, conversation)

    try:
        from app.config import settings
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": SKILL_EXTRACT_PROMPT.format(
                conversation=conversation[:8000]
            )}],
            max_tokens=2000,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON from response
        cleaned = _extract_json(raw)
        if not cleaned:
            return {"agent_id": agent_id, "extracted": 0, "skills": []}
        skills = json.loads(cleaned)
        if not isinstance(skills, list):
            skills = [skills]
    except Exception as e:
        log.warning(f"LLM skill extraction failed: {e}")
        return {"agent_id": agent_id, "extracted": 0, "skills": [], "error": str(e)}

    saved = []
    for sk in skills:
        if not isinstance(sk, dict) or not sk.get("name"):
            continue
        try:
            result = await _upsert_skill(db, agent_id, sk)
            saved.append(result)
        except Exception as e:
            log.warning(f"Failed to save skill '{sk.get('name')}': {e}")

    return {"agent_id": agent_id, "extracted": len(saved), "skills": saved}


@router.get("/skills")
async def list_skills(
    agent_id: str | None = None,
    tag: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all extracted skills."""
    conditions = ["s.is_active = true"]
    params: dict = {"lim": limit, "off": offset}
    if agent_id:
        conditions.append("a.name = :agent")
        params["agent"] = agent_id
    if tag:
        conditions.append("s.tags ? :tag")
        params["tag"] = tag

    rows = await db.execute(
        text(f"""SELECT s.id, a.name as agent_name, s.name, s.description,
                        s.trigger, s.tags, s.usage_count, s.version, s.updated_at
                 FROM skills s
                 LEFT JOIN agents a ON s.agent_id = a.id
                 WHERE {' AND '.join(conditions)}
                 ORDER BY s.usage_count DESC, s.updated_at DESC
                 LIMIT :lim OFFSET :off
        """),
        params,
    )
    skills = [dict(r._mapping) for r in rows.fetchall()]
    return {"count": len(skills), "skills": skills}


@router.get("/skills/{skill_name}")
async def get_skill(
    skill_name: str,
    agent_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Get a skill by name."""
    row = await db.execute(
        text("""SELECT s.*, a.name as agent_name
                 FROM skills s
                 JOIN agents a ON s.agent_id = a.id
                 WHERE s.name = :name AND a.name = :agent AND s.is_active = true
        """),
        {"name": skill_name, "agent": agent_id},
    )
    r = row.fetchone()
    if not r:
        raise HTTPException(404, f"Skill not found: {skill_name}")
    return dict(r._mapping)


@router.post("/skills/{skill_name}/use")
async def record_skill_use(
    skill_name: str,
    agent_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Record a skill usage."""
    await db.execute(
        text("""UPDATE skills SET usage_count = usage_count + 1, updated_at = :now
                 WHERE name = :name
                 AND agent_id = (SELECT id FROM agents WHERE name = :agent)
        """),
        {"name": skill_name, "agent": agent_id, "now": datetime.now(timezone.utc)},
    )
    await db.commit()
    return {"skill": skill_name, "status": "recorded"}


@router.delete("/skills/{skill_name}")
async def delete_skill(
    skill_name: str,
    agent_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a skill."""
    await db.execute(
        text("""UPDATE skills SET is_active = false, updated_at = :now
                 WHERE name = :name
                 AND agent_id = (SELECT id FROM agents WHERE name = :agent)
        """),
        {"name": skill_name, "agent": agent_id, "now": datetime.now(timezone.utc)},
    )
    await db.commit()
    return {"skill": skill_name, "status": "deleted"}


# ── Internal helpers ────────────────────────────────────────────────────────

async def _upsert_skill(db: AsyncSession, agent_id: str, skill_data: dict) -> dict:
    """Create or update a skill in the database."""
    name = skill_data["name"][:128]
    description = (skill_data.get("description") or "")[:2000]
    trigger = (skill_data.get("trigger") or "")[:2000]
    steps = (skill_data.get("steps") or "")[:10000]
    tags = skill_data.get("tags", [])
    importance = min(1.0, max(0.0, float(skill_data.get("importance", 0.5))))
    now = datetime.now(timezone.utc)

    # Build full SKILL.md content
    content = f"# {name}\n\n"
    if description:
        content += f"{description}\n\n"
    if trigger:
        content += f"## Trigger\n{trigger}\n\n"
    if steps:
        content += f"## Steps\n{steps}\n\n"
    if tags:
        content += f"## Tags\n{', '.join(tags)}\n"

    await _ensure_agent(db, agent_id)

    await db.execute(
        text("""INSERT INTO skills
                (id, agent_id, name, description, trigger, steps, content,
                 tags, is_active, version, created_at, updated_at)
                VALUES (gen_random_uuid(),
                        (SELECT id FROM agents WHERE name = :agent),
                        :name, :desc, :trigger, :steps, :content,
                        :tags, true, 1, :now, :now)
                ON CONFLICT (agent_id, name) DO UPDATE SET
                    description = :desc2, trigger = :trigger2, steps = :steps2,
                    content = :content2, tags = :tags2, version = skills.version + 1,
                    updated_at = :now2, is_active = true
                RETURNING id, name, description, tags, version
        """),
        {
            "agent": agent_id, "name": name, "desc": description,
            "trigger": trigger, "steps": steps, "content": content,
            "tags": json.dumps(tags), "now": now,
            "desc2": description, "trigger2": trigger, "steps2": steps,
            "content2": content, "tags2": json.dumps(tags), "now2": now,
        },
    )
    await db.commit()

    return {"name": name, "tags": tags, "version": 1}


async def _basic_extract(db, agent_id: str, conversation: str):
    """Fallback: basic pattern detection without LLM."""
    # Simple heuristic: look for repeated tool patterns
    lines = conversation.strip().split("\n")
    if len(lines) < 5:
        return {"agent_id": agent_id, "extracted": 0, "skills": []}

    # Detect common patterns
    skills_to_check = []

    # Check for git/commit patterns
    if any("git add" in l.lower() for l in lines):
        skills_to_check.append({
            "name": "git-commit-workflow",
            "description": "Standard git add, commit, push workflow",
            "trigger": "When ready to save changes to git",
            "steps": "1. `git add .` to stage all changes\n2. `git commit -m \"message\"` to commit\n3. `git push` to push to remote",
            "tags": ["git", "version-control", "workflow"],
            "importance": 0.7,
        })

    # Check for docker patterns
    if any("docker" in l.lower() for l in lines):
        skills_to_check.append({
            "name": "docker-workflow",
            "description": "Docker container and image management",
            "trigger": "When working with Docker containers",
            "steps": "1. `docker ps` to list running containers\n2. `docker build -t name .` to build\n3. `docker compose up -d` to start services",
            "tags": ["docker", "containers", "devops"],
            "importance": 0.6,
        })

    saved = []
    for sk in skills_to_check:
        try:
            result = await _upsert_skill(db, agent_id, sk)
            saved.append(result)
        except Exception as e:
            log.warning(f"Basic extract failed for '{sk['name']}': {e}")

    return {"agent_id": agent_id, "extracted": len(saved), "skills": saved, "mode": "basic"}


def _extract_json(text: str) -> str | None:
    """Extract JSON array or object from LLM response text."""
    # Try to find JSON in code fences
    import re
    m = re.search(r"```(?:json)?\s*(\[.*?\]|{.*?})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Try bare JSON
    for prefix in ("[", "{"):
        start = text.find(prefix)
        if start >= 0:
            end = text.rfind("]" if prefix == "[" else "}")
            if end > start:
                return text[start:end + 1]
    return None


def _get_llm():
    """Get LLM client if configured."""
    try:
        from app.llm import get_llm_client
        return get_llm_client()
    except Exception:
        return None


async def _ensure_agent(db, name: str):
    """Ensure an agent record exists."""
    row = await db.execute(text("SELECT id FROM agents WHERE name = :name"), {"name": name})
    if not row.fetchone():
        await db.execute(
            text("INSERT INTO agents (id, name, metadata) VALUES (gen_random_uuid(), :name, '{}'::jsonb)"),
            {"name": name},
        )
        await db.commit()
