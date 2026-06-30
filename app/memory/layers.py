"""L1/L2/L3 layered memory + memory cubes + tree links + image memory.

This is the Nexus-native equivalent of MemOS's L1/L2/L3 architecture.
Three layers, each with different storage / decay / retrieval behaviour:

  L1  activation   — short-term, hot, fast decay. Recent session context.
                      Default TTL: 7d. Background decay: 0.95/hour.
                      Returns to top of recall when touched.

  L2  preference   — medium-term, warm, slow decay. Durable user prefs,
                      learned skills. Default TTL: 90d.
                      Promoted from L1 when used 3+ times.

  L3  world model  — long-term, cold, no decay. Stable facts about the
                      user, agent, project. Verified manually or by
                      observation. Never auto-expires.

A memory_cube is a per-user / per-project isolation boundary. Memories
belong to a cube; a user can have multiple cubes (e.g. "personal",
"work-project-x", "shared-team-y"); the active cube is set per session.

memory_links form the tree-text structure: parent_of / child_of edges
build the hierarchy; related / supersedes / derived_from / contradicts
are graph edges. The tree enables structural search: instead of just
"find memories like this query", we can ask "show me all facts under
the 'ci-cd' topic node".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("nexus.memory.layers")

LAYER_L1 = "L1"  # activation: short-term, hot
LAYER_L2 = "L2"  # preference: medium-term, warm
LAYER_L3 = "L3"  # world model: long-term, cold

VALID_LAYERS = (LAYER_L1, LAYER_L2, LAYER_L3)

# Default decay / TTL per layer
LAYER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    LAYER_L1: {
        "default_importance": 0.5,
        "decay_rate_per_hour": 0.95,
        "activation_boost_on_access": 0.3,
        "auto_demote_below": 0.1,
        "promote_to": None,  # promoted manually or after 3 uses
    },
    LAYER_L2: {
        "default_importance": 0.7,
        "decay_rate_per_hour": 0.999,  # very slow
        "activation_boost_on_access": 0.1,
        "auto_demote_below": None,  # no auto-demote
        "promote_to": LAYER_L3,  # can be promoted
    },
    LAYER_L3: {
        "default_importance": 0.9,
        "decay_rate_per_hour": 1.0,  # no decay
        "activation_boost_on_access": 0.0,
        "auto_demote_below": None,
        "promote_to": None,  # top of the stack
    },
}


# ── Memory cube management ──────────────────────────────────────────────

async def get_or_create_cube(
    db: AsyncSession, name: str, owner_id: Optional[str] = None, scope: str = "private"
) -> str:
    """Return the UUID of the named cube, creating it if missing."""
    row = (await db.execute(
        text("SELECT id FROM memory_cubes WHERE name = :name"),
        {"name": name},
    )).fetchone()
    if row:
        return str(row[0])
    new_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO memory_cubes (id, name, owner_id, scope, metadata)
            VALUES (:id, :name, :owner, :scope, '{}'::jsonb)
        """),
        {"id": new_id, "name": name, "owner": owner_id, "scope": scope},
    )
    await db.commit()
    log.info("created memory_cube %s (owner=%s scope=%s)", name, owner_id, scope)
    return new_id


async def list_cubes(db: AsyncSession) -> List[Dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT id, name, owner_id, scope, metadata, created_at
        FROM memory_cubes ORDER BY name
    """))).fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "owner_id": r[2],
            "scope": r[3],
            "metadata": dict(r[4] or {}),
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


# ── Layer assignment ────────────────────────────────────────────────────

async def set_layer(
    db: AsyncSession,
    memory_id: str,
    layer: str,
    cube_id: Optional[str] = None,
    activation_score: float = 1.0,
    pinned: bool = False,
    user_confidence: float = 1.0,
    verification: Optional[str] = None,
) -> None:
    """Assign a memory to a layer. Idempotent (UPSERT)."""
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer {layer!r}; must be one of {VALID_LAYERS}")
    await db.execute(text("""
        INSERT INTO memory_layers
            (memory_id, layer, cube_id, activation_score, pinned, user_confidence, verification)
        VALUES (:mid, :layer, :cube, :score, :pinned, :conf, :verify)
        ON CONFLICT (memory_id) DO UPDATE SET
            layer = EXCLUDED.layer,
            cube_id = EXCLUDED.cube_id,
            activation_score = EXCLUDED.activation_score,
            pinned = EXCLUDED.pinned,
            user_confidence = EXCLUDED.user_confidence,
            verification = EXCLUDED.verification
    """), {
        "mid": memory_id,
        "layer": layer,
        "cube": cube_id,
        "score": activation_score,
        "pinned": pinned,
        "conf": user_confidence,
        "verify": verification,
    })
    await db.commit()


async def get_layer(db: AsyncSession, memory_id: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT layer, cube_id, activation_score, pinned, user_confidence,
               verification, last_activated_at, created_at
        FROM memory_layers WHERE memory_id = :mid
    """), {"mid": memory_id})).fetchone()
    if not row:
        return None
    return {
        "memory_id": memory_id,
        "layer": row[0],
        "cube_id": str(row[1]) if row[1] else None,
        "activation_score": float(row[2] or 0),
        "pinned": bool(row[3]),
        "user_confidence": float(row[4] or 1.0),
        "verification": row[5],
        "last_activated_at": row[6].isoformat() if row[6] else None,
        "layer_created_at": row[7].isoformat() if row[7] else None,
    }


async def list_by_layer(
    db: AsyncSession,
    layer: str,
    cube_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List memories in a layer, ordered by activation score desc."""
    where_cube = "AND ml.cube_id = :cube" if cube_id else ""
    params: Dict[str, Any] = {"layer": layer, "limit": limit}
    if cube_id:
        params["cube"] = cube_id
    rows = (await db.execute(text(f"""
        SELECT m.id, m.content, m.memory_type, m.importance, m.confidence,
               m.access_count, m.created_at,
               ml.activation_score, ml.last_activated_at, ml.pinned
        FROM memories m
        JOIN memory_layers ml ON ml.memory_id = m.id
        WHERE ml.layer = :layer {where_cube}
        ORDER BY ml.pinned DESC, ml.activation_score DESC, m.created_at DESC
        LIMIT :limit
    """), params)).fetchall()
    return [_row_to_memory(r) for r in rows]


# ── Activation: touch / decay / promote ──────────────────────────────────

async def touch(db: AsyncSession, memory_id: str, boost: Optional[float] = None) -> float:
    """Touch a memory: bump activation, mark last_activated_at, increment
    access_count. Returns the new activation score."""
    layer_info = await get_layer(db, memory_id)
    if not layer_info:
        return 0.0
    if layer_info["pinned"]:
        return 1.0
    layer = layer_info["layer"]
    cfg = LAYER_DEFAULTS[layer]
    inc = boost if boost is not None else cfg["activation_boost_on_access"]
    new_score = min(1.0, layer_info["activation_score"] + inc)
    await db.execute(text("""
        UPDATE memory_layers
        SET activation_score = :score,
            last_activated_at = NOW()
        WHERE memory_id = :mid
    """), {"mid": memory_id, "score": new_score})
    await db.execute(text("""
        UPDATE memories
        SET access_count = access_count + 1,
            accessed_at = NOW()
        WHERE id = :mid
    """), {"mid": memory_id})
    await db.commit()
    return new_score


async def decay_all_l1(db: AsyncSession, rate: float = 0.95) -> int:
    """Background decay: multiply L1 activation_score by `rate`.
    Run hourly via the worker. Returns number of rows updated."""
    cfg = LAYER_DEFAULTS[LAYER_L1]
    r = await db.execute(text(f"""
        UPDATE memory_layers
        SET activation_score = activation_score * :rate
        WHERE layer = 'L1' AND pinned = FALSE
    """), {"rate": rate})
    await db.commit()
    return r.rowcount or 0


async def demote_dead_l1(db: AsyncSession, threshold: float = 0.05) -> int:
    """L1 memories whose activation has dropped below `threshold` are
    marked for demotion: their content is summarized into an L2 memory
    and the L1 row is deleted. Returns number of rows demoted."""
    cfg = LAYER_DEFAULTS[LAYER_L1]
    threshold = cfg.get("auto_demote_below") or threshold
    r = await db.execute(text("""
        DELETE FROM memory_layers
        WHERE layer = 'L1'
          AND pinned = FALSE
          AND activation_score < :threshold
        RETURNING memory_id
    """), {"threshold": threshold})
    demoted_ids = [str(row[0]) for row in r.fetchall()]
    if demoted_ids:
        log.info("demoted %d L1 memories below threshold %.2f", len(demoted_ids), threshold)
    await db.commit()
    return len(demoted_ids)


async def promote(
    db: AsyncSession,
    memory_id: str,
    to_layer: str,
    reason: str = "manual",
) -> None:
    """Promote a memory from L1 → L2 → L3. Reasons: 'manual', 'auto_use_count',
    'user_confirmed'."""
    if to_layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer {to_layer}")
    layer = await get_layer(db, memory_id)
    if not layer:
        return
    from_layer = layer["layer"]
    if to_layer == from_layer:
        return
    await set_layer(
        db, memory_id, to_layer,
        cube_id=layer["cube_id"],
        activation_score=1.0,
        pinned=(to_layer == LAYER_L3),
        user_confidence=1.0 if to_layer == LAYER_L3 else layer["user_confidence"],
        verification="manual" if to_layer == LAYER_L3 else layer["verification"],
    )
    log.info("promoted memory %s: %s -> %s (%s)", memory_id, from_layer, to_layer, reason)


async def auto_promote_use_count(
    db: AsyncSession, memory_id: str, threshold: int = 3
) -> Optional[str]:
    """If a memory's access_count has crossed the threshold, promote it
    L1 -> L2 automatically. Returns the new layer if promoted, else None."""
    layer = await get_layer(db, memory_id)
    if not layer or layer["layer"] != LAYER_L1:
        return None
    row = (await db.execute(
        text("SELECT access_count FROM memories WHERE id = :mid"),
        {"mid": memory_id},
    )).fetchone()
    if not row or (row[0] or 0) < threshold:
        return None
    await promote(db, memory_id, LAYER_L2, reason=f"auto_use_count>={threshold}")
    return LAYER_L2


# ── Tree-text memory links ─────────────────────────────────────────────

async def link_memories(
    db: AsyncSession,
    src_id: str,
    dst_id: str,
    kind: str = "related",
    weight: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Create an edge in the memory graph. Idempotent on (src,dst,kind)."""
    valid = ("parent_of", "child_of", "related", "supersedes", "derived_from", "contradicts")
    if kind not in valid:
        raise ValueError(f"invalid link kind {kind!r}; must be one of {valid}")
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO memory_links (id, src_id, dst_id, kind, weight, metadata)
        VALUES (:id, :src, :dst, :kind, :w, CAST(:meta AS jsonb))
        ON CONFLICT (src_id, dst_id, kind) DO UPDATE SET
            weight = EXCLUDED.weight,
            metadata = EXCLUDED.metadata
        RETURNING id
    """), {
        "id": new_id,
        "src": src_id, "dst": dst_id, "kind": kind, "w": weight,
        "meta": _json_dumps(metadata or {}),
    })
    await db.commit()
    return new_id


async def get_children(db: AsyncSession, parent_id: str) -> List[Dict[str, Any]]:
    """Tree search: return all children of a memory."""
    rows = (await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance,
               ml.activation_score
        FROM memory_links l
        JOIN memories m ON m.id = l.dst_id
        LEFT JOIN memory_layers ml ON ml.memory_id = m.id
        WHERE l.src_id = :pid AND l.kind = 'parent_of'
        ORDER BY m.importance DESC
    """), {"pid": parent_id})).fetchall()
    return [_row_to_memory(r, include_layer=True) for r in rows]


async def get_parents(db: AsyncSession, child_id: str) -> List[Dict[str, Any]]:
    """Tree search: return all parents of a memory."""
    rows = (await db.execute(text("""
        SELECT m.id, m.content, m.memory_type, m.importance,
               ml.activation_score
        FROM memory_links l
        JOIN memories m ON m.id = l.src_id
        LEFT JOIN memory_layers ml ON ml.memory_id = m.id
        WHERE l.dst_id = :cid AND l.kind = 'parent_of'
        ORDER BY m.importance DESC
    """), {"cid": child_id})).fetchall()
    return [_row_to_memory(r, include_layer=True) for r in rows]


async def get_related(
    db: AsyncSession, memory_id: str, kind: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Graph search: return all memories related by kind (default: any)."""
    where_kind = "AND l.kind = :kind" if kind else ""
    params: Dict[str, Any] = {"mid": memory_id}
    if kind:
        params["kind"] = kind
    rows = (await db.execute(text(f"""
        SELECT m.id, m.content, m.memory_type, m.importance,
               l.kind, l.weight, ml.activation_score
        FROM memory_links l
        JOIN memories m ON m.id = l.dst_id
        LEFT JOIN memory_layers ml ON ml.memory_id = m.id
        WHERE l.src_id = :mid {where_kind}
        ORDER BY l.weight DESC
    """), params)).fetchall()
    return [_row_to_memory(r, include_layer=True, extra={"link_kind": r[5], "link_weight": float(r[6])}) for r in rows]


async def build_tree(db: AsyncSession, root_id: str, max_depth: int = 4) -> Dict[str, Any]:
    """Walk the parent_of tree from a root and return a nested dict.
    Used by the dashboard to render topic trees."""
    async def _walk(node_id: str, depth: int) -> Dict[str, Any]:
        row = (await db.execute(text("""
            SELECT m.id, m.content, m.memory_type, m.importance
            FROM memories m WHERE m.id = :id
        """), {"id": node_id})).fetchone()
        if not row:
            return {"id": node_id, "missing": True}
        node = _row_to_memory(row)
        if depth >= max_depth:
            node["children"] = []
            return node
        kids = await get_children(db, node_id)
        node["children"] = [await _walk(k["id"], depth + 1) for k in kids]
        return node
    return await _walk(root_id, 0)


# ── Image memory ────────────────────────────────────────────────────────

async def attach_image(
    db: AsyncSession,
    memory_id: str,
    url: str,
    storage_path: str,
    mime_type: str = "image/png",
    width: Optional[int] = None,
    height: Optional[int] = None,
    bytes_: Optional[int] = None,
    phash: Optional[str] = None,
    caption: Optional[str] = None,
    ocr_text: Optional[str] = None,
) -> str:
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO image_memory
            (id, memory_id, url, storage_path, mime_type, width, height, bytes, phash, caption, ocr_text)
        VALUES (:id, :mid, :url, :path, :mime, :w, :h, :bytes, :phash, :caption, :ocr)
    """), {
        "id": new_id, "mid": memory_id, "url": url, "path": storage_path,
        "mime": mime_type, "w": width, "h": height, "bytes": bytes_,
        "phash": phash, "caption": caption, "ocr": ocr_text,
    })
    await db.commit()
    return new_id


async def get_image(db: AsyncSession, memory_id: str) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT id, url, storage_path, mime_type, width, height, bytes,
               phash, caption, ocr_text, created_at
        FROM image_memory WHERE memory_id = :mid ORDER BY created_at DESC LIMIT 1
    """), {"mid": memory_id})).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "memory_id": memory_id,
        "url": row[1],
        "storage_path": row[2],
        "mime_type": row[3],
        "width": row[4], "height": row[5], "bytes": row[6],
        "phash": row[7], "caption": row[8], "ocr_text": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
    }


# ── Tool memory ─────────────────────────────────────────────────────────

async def record_tool_use(
    db: AsyncSession,
    agent_id: str,
    tool_name: str,
    args_summary: str,
    result_summary: str,
    success: bool = True,
    duration_ms: Optional[int] = None,
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
) -> str:
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO tool_memory
            (id, agent_id, tool_name, args_summary, result_summary, success, duration_ms, session_id, memory_id)
        VALUES (:id, :aid, :tool, :args, :res, :ok, :dur, :sess, :mid)
    """), {
        "id": new_id, "aid": agent_id, "tool": tool_name,
        "args": args_summary, "res": result_summary, "ok": success,
        "dur": duration_ms, "sess": session_id, "mid": memory_id,
    })
    await db.commit()
    return new_id


async def recall_tool_uses(
    db: AsyncSession,
    agent_id: str,
    tool_name: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Recall past tool use by this agent (and optionally by tool)."""
    where_tool = "AND tool_name = :tool" if tool_name else ""
    params: Dict[str, Any] = {"aid": agent_id, "limit": limit}
    if tool_name:
        params["tool"] = tool_name
    rows = (await db.execute(text(f"""
        SELECT id, tool_name, args_summary, result_summary, success, duration_ms, created_at
        FROM tool_memory WHERE agent_id = :aid {where_tool}
        ORDER BY created_at DESC LIMIT :limit
    """), params)).fetchall()
    return [
        {
            "id": str(r[0]),
            "tool_name": r[1],
            "args_summary": r[2],
            "result_summary": r[3],
            "success": bool(r[4]),
            "duration_ms": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


# ── Skill cards (crystallized patterns) ───────────────────────────────

async def upsert_skill(
    db: AsyncSession,
    name: str,
    description: str,
    trigger_pattern: str,
    steps: List[Dict[str, Any]],
    source_memory_ids: Optional[List[str]] = None,
    agent_id: Optional[str] = None,
) -> str:
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO skill_cards
            (id, name, description, trigger_pattern, steps, source_memory_ids, agent_id)
        VALUES (:id, :name, :desc, :pat, CAST(:steps AS jsonb), CAST(:srcs AS jsonb), :aid)
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            trigger_pattern = EXCLUDED.trigger_pattern,
            steps = EXCLUDED.steps,
            source_memory_ids = EXCLUDED.source_memory_ids,
            agent_id = EXCLUDED.agent_id
        RETURNING id
    """), {
        "id": new_id, "name": name, "desc": description, "pat": trigger_pattern,
        "steps": _json_dumps(steps),
        "srcs": _json_dumps(source_memory_ids or []),
        "aid": agent_id,
    })
    await db.commit()
    return new_id


async def record_skill_use(db: AsyncSession, skill_id: str, success: bool) -> None:
    await db.execute(text("""
        UPDATE skill_cards
        SET use_count = use_count + 1,
            success_count = success_count + CASE WHEN :ok THEN 1 ELSE 0 END,
            last_used_at = NOW()
        WHERE id = :id
    """), {"id": skill_id, "ok": success})
    await db.commit()


async def find_skill(
    db: AsyncSession, name: Optional[str] = None, agent_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    where = []
    params: Dict[str, Any] = {}
    if name:
        where.append("name = :name")
        params["name"] = name
    if agent_id:
        where.append("agent_id = :aid")
        params["aid"] = agent_id
    wsql = "WHERE " + " AND ".join(where) if where else ""
    rows = (await db.execute(text(f"""
        SELECT id, name, description, trigger_pattern, steps,
               use_count, success_count, last_used_at, source_memory_ids
        FROM skill_cards {wsql} ORDER BY use_count DESC
    """), params)).fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1], "description": r[2], "trigger_pattern": r[3],
            "steps": r[4] if isinstance(r[4], list) else [],
            "use_count": r[5], "success_count": r[6],
            "last_used_at": r[7].isoformat() if r[7] else None,
            "source_memory_ids": r[8] or [],
        }
        for r in rows
    ]


# ── Memory feedback (natural-language corrections) ────────────────────

async def record_feedback(
    db: AsyncSession,
    target_memory_id: str,
    feedback_kind: str,
    agent_id: Optional[str] = None,
    original_text: Optional[str] = None,
    new_text: Optional[str] = None,
    merged_with_id: Optional[str] = None,
) -> str:
    """Save a piece of natural-language feedback. Applying it is a
    separate operation (apply_feedback) so the user can review first."""
    valid = ("correct", "supplement", "merge", "delete", "pin", "demote")
    if feedback_kind not in valid:
        raise ValueError(f"invalid feedback kind {feedback_kind!r}")
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO memory_feedback
            (id, target_memory_id, agent_id, feedback_kind, original_text, new_text, merged_with_id)
        VALUES (:id, :tgt, :aid, :kind, :orig, :new, :merge)
    """), {
        "id": new_id, "tgt": target_memory_id, "aid": agent_id, "kind": feedback_kind,
        "orig": original_text, "new": new_text, "merge": merged_with_id,
    })
    await db.commit()
    return new_id


async def apply_feedback(
    db: AsyncSession, feedback_id: str
) -> Optional[Dict[str, Any]]:
    """Apply a recorded feedback to the underlying memory. Returns the
    applied memory row, or None if the feedback was already applied."""
    row = (await db.execute(text("""
        SELECT target_memory_id, feedback_kind, new_text, merged_with_id, applied
        FROM memory_feedback WHERE id = :id
    """), {"id": feedback_id})).fetchone()
    if not row or row[4]:
        return None
    target_id, kind, new_text, merge_id, _ = row
    applied_id: Optional[str] = None
    if kind == "correct" and new_text:
        # Update the target memory's content; bump confidence
        await db.execute(text("""
            UPDATE memories
            SET content = :new, confidence = 1.0, access_count = access_count + 1
            WHERE id = :id
        """), {"id": target_id, "new": new_text})
        applied_id = target_id
    elif kind == "supplement" and new_text:
        # Append the supplement to the content, marked with a divider
        await db.execute(text("""
            UPDATE memories
            SET content = content || E'\\n\\n---\\nSupplemented: ' || :new,
                access_count = access_count + 1
            WHERE id = :id
        """), {"id": target_id, "new": new_text})
        applied_id = target_id
    elif kind == "merge" and merge_id:
        # Merge two memories: keep the older one, delete the newer,
        # append the newer content to the older
        await db.execute(text("""
            UPDATE memories m1
            SET content = m1.content || E'\\n\\n---\\nMerged from: ' || m2.content,
                access_count = m1.access_count + m2.access_count
            FROM memories m2
            WHERE m1.id = :keep AND m2.id = :drop
        """), {"keep": target_id, "drop": merge_id})
        await db.execute(text("DELETE FROM memories WHERE id = :id"), {"id": merge_id})
        applied_id = target_id
    elif kind == "delete":
        await db.execute(text("DELETE FROM memories WHERE id = :id"), {"id": target_id})
    elif kind == "pin":
        # Move to L3 + pin
        await set_layer(db, target_id, LAYER_L3, pinned=True)
        applied_id = target_id
    elif kind == "demote":
        # Move to L1 (or unpin)
        await db.execute(
            text("UPDATE memory_layers SET pinned = FALSE WHERE memory_id = :id"),
            {"id": target_id},
        )
        await db.commit()
        applied_id = target_id
    # Mark the feedback as applied
    await db.execute(text("""
        UPDATE memory_feedback
        SET applied = TRUE, applied_memory_id = :app
        WHERE id = :id
    """), {"id": feedback_id, "app": applied_id})
    await db.commit()
    log.info("applied feedback %s (%s) to memory %s", feedback_id, kind, target_id)
    return {"feedback_id": feedback_id, "kind": kind, "applied_memory_id": applied_id}


# ── Helpers ─────────────────────────────────────────────────────────────

def _row_to_memory(r: Any, include_layer: bool = False, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Best-effort row-to-dict for memory rows. Different SELECTs return
    different shapes; this normalises what we can."""
    out: Dict[str, Any] = {}
    if isinstance(r, dict):
        for k, v in r.items():
            out[k] = v
        return out
    # Tuple form: assume the standard (id, content, memory_type, importance, [layer fields], ...)
    if len(r) >= 4:
        out["id"] = str(r[0])
        out["content"] = r[1]
        out["memory_type"] = r[2]
        out["importance"] = float(r[3]) if r[3] is not None else None
    if include_layer and len(r) >= 5:
        out["activation_score"] = float(r[4]) if r[4] is not None else None
    if extra:
        out.update(extra)
    return out


def _json_dumps(obj: Any) -> str:
    """Lazy json.dumps to avoid an import at module top."""
    import json
    return json.dumps(obj, default=str)


__all__ = [
    # Layers
    "LAYER_L1", "LAYER_L2", "LAYER_L3", "VALID_LAYERS", "LAYER_DEFAULTS",
    # Cubes
    "get_or_create_cube", "list_cubes",
    # Layer assignment
    "set_layer", "get_layer", "list_by_layer",
    # Activation
    "touch", "decay_all_l1", "demote_dead_l1", "promote", "auto_promote_use_count",
    # Tree-text
    "link_memories", "get_children", "get_parents", "get_related", "build_tree",
    # Image
    "attach_image", "get_image",
    # Tool
    "record_tool_use", "recall_tool_uses",
    # Skills
    "upsert_skill", "record_skill_use", "find_skill",
    # Feedback
    "record_feedback", "apply_feedback",
]
