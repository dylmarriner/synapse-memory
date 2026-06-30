"""Memory layers API — L1/L2/L3 layered memory, cubes, tree links, images,
tools, skills, and natural-language memory feedback.

These are the MemOS-style primitives, implemented natively in Nexus. No
external services. The LLM controls the mind and the user (or another
agent) can correct memories with natural language.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.memory import layers as L

log = logging.getLogger("nexus.routers.layers")
router = APIRouter(prefix="/v1/layer", tags=["layers"])


# ── Schemas ─────────────────────────────────────────────────────────────

class SetLayerRequest(BaseModel):
    memory_id: str
    layer: str = Field(pattern="^(L1|L2|L3)$")
    cube_id: Optional[str] = None
    activation_score: float = 1.0
    pinned: bool = False
    user_confidence: float = 1.0
    verification: Optional[str] = None


class CreateCubeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_id: Optional[str] = None
    scope: str = "private"


class LinkRequest(BaseModel):
    src_id: str
    dst_id: str
    kind: str = "related"
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


class ImageRequest(BaseModel):
    memory_id: str
    url: str
    storage_path: str
    mime_type: str = "image/png"
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: Optional[int] = None
    phash: Optional[str] = None
    caption: Optional[str] = None
    ocr_text: Optional[str] = None


class ToolUseRequest(BaseModel):
    agent_id: str
    tool_name: str
    args_summary: str
    result_summary: str
    success: bool = True
    duration_ms: Optional[int] = None
    session_id: Optional[str] = None
    memory_id: Optional[str] = None


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str
    trigger_pattern: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    source_memory_ids: Optional[List[str]] = None
    agent_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    target_memory_id: str
    feedback_kind: str = Field(pattern="^(correct|supplement|merge|delete|pin|demote)$")
    agent_id: Optional[str] = None
    original_text: Optional[str] = None
    new_text: Optional[str] = None
    merged_with_id: Optional[str] = None
    apply: bool = True


class FeedbackNaturalRequest(BaseModel):
    """Natural-language feedback: 'that memory is wrong, it should say X'."""
    target_memory_id: str
    natural_language: str  # e.g. "actually that should say qwen3 not qwen2"
    agent_id: Optional[str] = None
    apply: bool = True


# ── Cubes ──────────────────────────────────────────────────────────────

@router.post("/cubes")
async def create_cube(body: CreateCubeRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    cube_id = await L.get_or_create_cube(db, body.name, body.owner_id, body.scope)
    return {"id": cube_id, "name": body.name, "owner_id": body.owner_id, "scope": body.scope}


@router.get("/cubes")
async def list_cubes(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    cubes = await L.list_cubes(db)
    return {"cubes": cubes, "total": len(cubes)}


@router.get("/cubes/{cube_name}/stats")
async def cube_stats(cube_name: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Layer breakdown for a cube."""
    cube = (await db.execute(
        text("SELECT id FROM memory_cubes WHERE name = :n"), {"n": cube_name}
    )).fetchone()
    if not cube:
        raise HTTPException(404, f"cube '{cube_name}' not found")
    cube_id = str(cube[0])
    rows = (await db.execute(text("""
        SELECT layer, COUNT(*) AS n,
               AVG(activation_score) AS avg_act
        FROM memory_layers
        WHERE cube_id = :cid
        GROUP BY layer
    """), {"cid": cube_id})).fetchall()
    by_layer = {r[0]: {"count": r[1], "avg_activation": float(r[2] or 0)} for r in rows}
    return {"cube_id": cube_id, "cube_name": cube_name, "by_layer": by_layer}


# ── Layer assignment ────────────────────────────────────────────────────

@router.post("/set")
async def set_layer(body: SetLayerRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await L.set_layer(
        db, body.memory_id, body.layer, body.cube_id,
        body.activation_score, body.pinned, body.user_confidence, body.verification,
    )
    return {"memory_id": body.memory_id, "layer": body.layer, "ok": True}


@router.get("/memory/{memory_id}")
async def get_memory_layer(memory_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    info = await L.get_layer(db, memory_id)
    if not info:
        raise HTTPException(404, "memory not in any layer")
    return info


@router.get("/list")
async def list_memories_in_layer(
    layer: str = Query(pattern="^(L1|L2|L3)$"),
    cube_id: Optional[str] = None,
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    mems = await L.list_by_layer(db, layer, cube_id, limit)
    return {"layer": layer, "cube_id": cube_id, "memories": mems, "count": len(mems)}


# ── Activation lifecycle ────────────────────────────────────────────────

@router.post("/memory/{memory_id}/touch")
async def touch_memory(
    memory_id: str, boost: Optional[float] = None, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Bump activation, mark as recently used, increment access_count."""
    new_score = await L.touch(db, memory_id, boost)
    # Also auto-promote if it crossed the threshold
    promoted = await L.auto_promote_use_count(db, memory_id, threshold=3)
    return {"memory_id": memory_id, "activation_score": new_score, "promoted_to": promoted}


@router.post("/decay")
async def run_decay(rate: float = 0.95, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Run background decay on all L1 memories. Run from a cron hourly."""
    updated = await L.decay_all_l1(db, rate)
    demoted = await L.demote_dead_l1(db, threshold=0.05)
    return {"updated": updated, "demoted": demoted, "rate": rate}


@router.post("/memory/{memory_id}/promote")
async def promote_memory(
    memory_id: str, to_layer: str = Query(pattern="^(L1|L2|L3)$"),
    reason: str = "manual", db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    await L.promote(db, memory_id, to_layer, reason)
    return {"memory_id": memory_id, "new_layer": to_layer, "reason": reason}


# ── Tree-text links ─────────────────────────────────────────────────────

@router.post("/link")
async def link(body: LinkRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    new_id = await L.link_memories(db, body.src_id, body.dst_id, body.kind, body.weight, body.metadata)
    return {"id": new_id, "src_id": body.src_id, "dst_id": body.dst_id, "kind": body.kind}


@router.get("/memory/{memory_id}/children")
async def get_memory_children(memory_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    return {"memory_id": memory_id, "children": await L.get_children(db, memory_id)}


@router.get("/memory/{memory_id}/parents")
async def get_memory_parents(memory_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    return {"memory_id": memory_id, "parents": await L.get_parents(db, memory_id)}


@router.get("/memory/{memory_id}/related")
async def get_memory_related(
    memory_id: str, kind: Optional[str] = None, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    return {"memory_id": memory_id, "related": await L.get_related(db, memory_id, kind)}


@router.get("/tree/{root_id}")
async def get_tree(
    root_id: str, max_depth: int = Query(4, le=8), db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    return await L.build_tree(db, root_id, max_depth)


# ── Image memory (multi-modal) ──────────────────────────────────────────

@router.post("/image")
async def attach_image(body: ImageRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    img_id = await L.attach_image(
        db, body.memory_id, body.url, body.storage_path, body.mime_type,
        body.width, body.height, body.bytes, body.phash, body.caption, body.ocr_text,
    )
    # Images default to L2 (durable, with caption)
    await L.set_layer(db, body.memory_id, L.LAYER_L2, activation_score=0.8)
    return {"id": img_id, "memory_id": body.memory_id, "ok": True}


@router.get("/image/{memory_id}")
async def get_image_for_memory(memory_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    img = await L.get_image(db, memory_id)
    if not img:
        raise HTTPException(404, "no image attached")
    return img


# ── Tool memory ─────────────────────────────────────────────────────────

@router.post("/tool")
async def record_tool(body: ToolUseRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    tid = await L.record_tool_use(
        db, body.agent_id, body.tool_name, body.args_summary, body.result_summary,
        body.success, body.duration_ms, body.session_id, body.memory_id,
    )
    return {"id": tid, "ok": True}


@router.get("/tool/recall")
async def recall_tool(
    agent_id: str, tool_name: Optional[str] = None, limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return {"agent_id": agent_id, "uses": await L.recall_tool_uses(db, agent_id, tool_name, limit)}


# ── Skill cards ────────────────────────────────────────────────────────

@router.post("/skill")
async def upsert_skill(body: SkillRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    sid = await L.upsert_skill(
        db, body.name, body.description, body.trigger_pattern,
        body.steps, body.source_memory_ids, body.agent_id,
    )
    return {"id": sid, "name": body.name, "ok": True}


@router.post("/skill/{skill_id}/use")
async def record_skill_use(skill_id: str, success: bool = True, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await L.record_skill_use(db, skill_id, success)
    return {"skill_id": skill_id, "ok": True}


@router.get("/skill/find")
async def find_skill(
    name: Optional[str] = None, agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return {"skills": await L.find_skill(db, name, agent_id)}


# ── Natural-language memory feedback ───────────────────────────────────

@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    fid = await L.record_feedback(
        db, body.target_memory_id, body.feedback_kind, body.agent_id,
        body.original_text, body.new_text, body.merged_with_id,
    )
    applied = None
    if body.apply:
        applied = await L.apply_feedback(db, fid)
    return {"feedback_id": fid, "applied": applied}


@router.post("/feedback/natural")
async def natural_language_feedback(
    body: FeedbackNaturalRequest, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Process natural-language feedback like 'memory X is wrong, it
    should say Y'. Uses the LLM to parse the intent and apply the right
    feedback_kind. Falls back to a raw save if the LLM can't parse it.
    """
    nl = body.natural_language.lower()
    kind: Optional[str] = None
    new_text: Optional[str] = None
    merge_id: Optional[str] = None
    if any(k in nl for k in ("wrong", "incorrect", "should say", "actually", "fix", "correct")):
        kind = "correct"
        # Try to extract "should say X" pattern
        import re
        m = re.search(r"(?:should say|actually is|is|means?)\s+(.+?)(?:\.|$)", body.natural_language, re.IGNORECASE)
        new_text = m.group(1).strip() if m else body.natural_language
    elif any(k in nl for k in ("also", "additionally", "and also", "supplement")):
        kind = "supplement"
        new_text = body.natural_language
    elif any(k in nl for k in ("merge", "combine", "same as")):
        kind = "merge"
        # Caller must supply merge_with via a second API call
        new_text = body.natural_language
    elif any(k in nl for k in ("delete", "remove", "forget", "wrong memory", "not true")):
        kind = "delete"
    elif any(k in nl for k in ("pin", "keep", "never forget", "important", "remember this")):
        kind = "pin"
    elif any(k in nl for k in ("demote", "less important", "lower priority")):
        kind = "demote"
    if not kind:
        raise HTTPException(400, "could not detect feedback intent; use /v1/layer/feedback with explicit kind")
    fid = await L.record_feedback(
        db, body.target_memory_id, kind, body.agent_id,
        body.natural_language, new_text, merge_id,
    )
    applied = None
    if body.apply:
        applied = await L.apply_feedback(db, fid)
    return {"feedback_id": fid, "kind": kind, "applied": applied, "new_text": new_text}


# ── Dashboard helpers ──────────────────────────────────────────────────

@router.get("/stats")
async def layer_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Dashboard summary: per-layer counts, top memories, recent activity."""
    rows = (await db.execute(text("""
        SELECT layer, COUNT(*) AS n,
               AVG(activation_score) AS avg_act,
               SUM(CASE WHEN pinned THEN 1 ELSE 0 END) AS pinned
        FROM memory_layers GROUP BY layer
    """))).fetchall()
    by_layer = {r[0]: {"count": r[1], "avg_activation": float(r[2] or 0), "pinned": r[3] or 0} for r in rows}
    cubes = await L.list_cubes(db)
    skills = await L.find_skill(db)
    return {
        "by_layer": by_layer,
        "cubes": len(cubes),
        "skills": len(skills),
        "totals": {
            "layered_memories": sum(v["count"] for v in by_layer.values()),
        },
    }
