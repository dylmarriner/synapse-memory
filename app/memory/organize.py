"""LLM-assisted memory organizer for linking, layering, and safe merging."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.decompose import decompose_large_memories
from app.memory.layers import link_memories, set_layer
from app.memory.merge import merge_memories_by_superseding

log = logging.getLogger("nexus.memory.organize")

VALID_LINK_KINDS = {"related", "derived_from", "contradicts", "parent_of"}
VALID_LAYERS = {"L2", "L3"}


async def organize_memories(db: AsyncSession) -> Dict[str, int]:
    stats: Dict[str, int] = {
        "organizer_candidate_pairs": 0,
        "organizer_clusters": 0,
        "organizer_links_created": 0,
        "organizer_merges": 0,
        "organizer_layers_updated": 0,
    }

    # Decompose bundled/oversized memories into atomic facts first, so the
    # clustering pass below sees the smaller, more precise memories rather
    # than one giant blob that would never cleanly merge or link with anything.
    stats.update(await decompose_large_memories(db))

    if not settings.llm_memory_organizer_enabled:
        return stats

    from app.llm import get_llm_client
    llm = get_llm_client()
    if llm is None:
        return stats

    clusters = await _candidate_clusters(db)
    stats["organizer_candidate_pairs"] = sum(max(0, len(c) - 1) for c in clusters)
    if not clusters:
        return stats

    for cluster in clusters:
        payload = await _classify_cluster(cluster, llm)
        if not payload:
            continue
        stats["organizer_clusters"] += 1
        applied = await _apply_cluster(db, cluster, payload)
        for key, value in applied.items():
            stats[key] = stats.get(key, 0) + value

    return stats


async def _candidate_clusters(db: AsyncSession) -> List[List[Dict[str, Any]]]:
    threshold = settings.llm_memory_organizer_similarity_threshold
    limit = settings.llm_memory_organizer_pair_limit
    rows = (await db.execute(text(f"""
        SELECT a.id AS src_id,
               b.id AS dst_id,
               1 - (a.embedding <=> b.embedding) AS similarity
        FROM memories a
        JOIN memories b ON b.id > a.id
            AND b.agent_id IS NOT DISTINCT FROM a.agent_id
        WHERE a.superseded_by IS NULL
          AND b.superseded_by IS NULL
          AND a.embedding IS NOT NULL
          AND b.embedding IS NOT NULL
          AND a.memory_type != 'lesson'
          AND b.memory_type != 'lesson'
          AND 1 - (a.embedding <=> b.embedding) >= {threshold}
        ORDER BY similarity DESC
        LIMIT {limit}
    """))).fetchall()
    if not rows:
        return []

    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    node_ids: Set[str] = set()
    for row in rows:
        a = str(row.src_id)
        b = str(row.dst_id)
        node_ids.add(a)
        node_ids.add(b)
        union(a, b)

    groups: Dict[str, List[str]] = defaultdict(list)
    for node_id in node_ids:
        groups[find(node_id)].append(node_id)

    max_cluster = max(2, int(settings.llm_memory_organizer_max_cluster_size))
    out: List[List[Dict[str, Any]]] = []
    for ids in groups.values():
        limited = ids[:max_cluster]
        mem_rows = (await db.execute(text("""
            SELECT id, agent_id, content, memory_type, importance, confidence,
                   access_count, created_at, metadata
            FROM memories
            WHERE id = ANY(CAST(:ids AS uuid[]))
              AND superseded_by IS NULL
            ORDER BY importance DESC, created_at DESC
        """), {"ids": limited})).fetchall()
        cluster = [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "content": r.content,
                "memory_type": r.memory_type,
                "importance": float(r.importance or 0.0),
                "confidence": float(r.confidence or 0.0),
                "access_count": int(r.access_count or 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "metadata": dict(r.metadata or {}),
            }
            for r in mem_rows
        ]
        if len(cluster) >= 2:
            out.append(cluster)
    return out


async def _classify_cluster(cluster: List[Dict[str, Any]], llm) -> Optional[Dict[str, Any]]:
    items = "\n".join(
        f"- id={m['id']} type={m['memory_type']} importance={m['importance']:.2f} access={m['access_count']} text={m['content'][:500]}"
        for m in cluster
    )
    prompt = f"""
You are the memory-organizing part of a conscious mind.

Rules:
- Never delete anything.
- Only mark a memory as a duplicate if it is the same underlying fact, instruction, or event and should be merged into a single survivor.
- If two memories are merely connected, create links instead of merging.
- Prefer conservative output. If unsure, emit fewer merges.
- You may suggest stable layer placement only for durable memories: L2 or L3.

Return minified JSON with this exact shape:
{{
  "duplicates": [{{"keep_id":"...","drop_id":"...","confidence":0.0,"reason":"..."}}],
  "links": [{{"src_id":"...","dst_id":"...","kind":"related|derived_from|contradicts|parent_of","weight":0.0,"reason":"..."}}],
  "layer_updates": [{{"memory_id":"...","layer":"L2|L3","reason":"..."}}]
}}

Cluster:
{items}
""".strip()
    try:
        resp = await llm.chat.completions.create(
            model=settings.mind_llm_model or settings.llm_model,
            messages=[
                {"role": "system", "content": "You are a precise memory organizer. Output only JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0,
            timeout=30,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        log.debug("organizer classify failed: %s", e)
        return None


async def _apply_cluster(db: AsyncSession, cluster: List[Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, int]:
    stats = {
        "organizer_links_created": 0,
        "organizer_merges": 0,
        "organizer_layers_updated": 0,
    }
    valid_ids = {m["id"] for m in cluster}
    merged_ids: Set[str] = set()

    for item in payload.get("duplicates") or []:
        if not isinstance(item, dict):
            continue
        keep_id = str(item.get("keep_id") or "")
        drop_id = str(item.get("drop_id") or "")
        if keep_id not in valid_ids or drop_id not in valid_ids or keep_id == drop_id:
            continue
        if keep_id in merged_ids or drop_id in merged_ids:
            continue
        confidence = _coerce_float(item.get("confidence"), default=0.9)
        reason = str(item.get("reason") or "llm duplicate classification")[:500]
        merged = await merge_memories_by_superseding(db, keep_id, drop_id, source="llm-organizer", reason=reason, confidence=confidence)
        if merged:
            stats["organizer_merges"] += 1
            merged_ids.add(drop_id)

    for item in payload.get("links") or []:
        if not isinstance(item, dict):
            continue
        src_id = str(item.get("src_id") or "")
        dst_id = str(item.get("dst_id") or "")
        kind = str(item.get("kind") or "related")
        if src_id not in valid_ids or dst_id not in valid_ids or src_id == dst_id:
            continue
        if src_id in merged_ids or dst_id in merged_ids or kind not in VALID_LINK_KINDS:
            continue
        weight = _coerce_float(item.get("weight"), default=0.7)
        reason = str(item.get("reason") or "")[:500]
        await link_memories(db, src_id, dst_id, kind=kind, weight=weight, metadata={"source": "llm-organizer", "reason": reason})
        stats["organizer_links_created"] += 1
        if kind == "related":
            await link_memories(db, dst_id, src_id, kind=kind, weight=weight, metadata={"source": "llm-organizer", "reason": reason})
            stats["organizer_links_created"] += 1
        elif kind == "parent_of":
            await link_memories(db, dst_id, src_id, kind="child_of", weight=weight, metadata={"source": "llm-organizer", "reason": reason})
            stats["organizer_links_created"] += 1

    for item in payload.get("layer_updates") or []:
        if not isinstance(item, dict):
            continue
        memory_id = str(item.get("memory_id") or "")
        layer = str(item.get("layer") or "")
        if memory_id not in valid_ids or memory_id in merged_ids or layer not in VALID_LAYERS:
            continue
        reason = str(item.get("reason") or "llm organizer")[:200]
        await set_layer(
            db,
            memory_id,
            layer,
            activation_score=0.8 if layer == "L2" else 1.0,
            verification=reason if layer == "L3" else None,
        )
        stats["organizer_layers_updated"] += 1

    return stats


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return default
