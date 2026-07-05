"""Structured memory formatting for LLM prompts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _short(text: str, limit: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "…"


def _age_label(iso: Optional[str]) -> str:
    if not iso:
        return "?d"
    try:
        if isinstance(iso, str):
            ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        else:
            ts = iso
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - ts
        days = delta.days
        if days < 0:
            return "future"
        if days == 0:
            return "today"
        if days < 7:
            return f"{days}d"
        if days < 30:
            return f"{days // 7}w"
        if days < 365:
            return f"{days // 30}mo"
        return f"{days // 365}y"
    except Exception:
        return "?d"


def _imp_bar(imp: float) -> str:
    if imp is None:
        return "▄"
    levels = "▁▂▃▄▅▆▇█"
    idx = max(0, min(len(levels) - 1, int(imp * len(levels) - 0.0001)))
    return levels[idx]


def format_memories_brief(
    memories: List[Dict[str, Any]],
    *,
    char_limit: int = 140,
    max_items: int = 16,
) -> str:
    if not memories:
        return "(no memories)"
    lines = []
    for m in memories[:max_items]:
        mid = m.get("id", "?")[:8]
        age = _age_label(m.get("created_at"))
        mtype = (m.get("memory_type") or "obs")[:3]
        scope = (m.get("agent_id") or m.get("scope") or "—")
        if isinstance(scope, str) and len(scope) > 12:
            scope = scope[:12]
        layer = m.get("layer") or (m.get("metadata") or {}).get("layer") or "-"
        rels = int(m.get("relation_count") or (m.get("metadata") or {}).get("relation_count") or 0)
        content = _short(m.get("content") or "", char_limit)
        lines.append(f"[{age}|{mtype}|{layer}|{scope}|r{rels}] {mid}  {content}")
    return "\n".join(lines)


def format_memories_structured(
    memories: List[Dict[str, Any]],
    *,
    char_limit: int = 280,
    max_items: int = 16,
    related_lookup: Optional[Dict[str, List[str]]] = None,
) -> str:
    if not memories:
        return "(no memories)"
    related_lookup = related_lookup or {}

    total = len(memories)
    ages = [_age_label(m.get("created_at")) for m in memories]
    header = f"# {total} memories"
    if any(a != "?d" for a in ages):
        try:
            days = [int(a.rstrip("dwmo")) if a and a[0].isdigit() else None for a in ages]
            valid = [d for d in days if d is not None]
            if valid:
                header += f"  ·  range {min(valid)}d→{max(valid)}d"
        except Exception:
            pass

    blocks = [header, ""]
    for m in memories[:max_items]:
        mid_full = m.get("id", "?")
        mid = mid_full[:8]
        mtype = (m.get("memory_type") or "obs")
        age = _age_label(m.get("created_at"))
        imp = m.get("importance")
        if imp is None:
            imp = m.get("confidence", 0.5)
        try:
            imp_f = float(imp)
        except Exception:
            imp_f = 0.5
        bar = _imp_bar(imp_f)
        content = _short(m.get("content") or "", char_limit)
        layer = m.get("layer") or (m.get("metadata") or {}).get("layer") or "-"
        relation_count = int(m.get("relation_count") or (m.get("metadata") or {}).get("relation_count") or 0)
        modes = "+".join((m.get("matched_by") or [])[:3]) or "-"

        rel = related_lookup.get(mid_full) or related_lookup.get(mid)
        rel_line = ""
        if rel:
            rel_short = [r[:8] for r in rel[:3]]
            rel_line = f"\n  ↳ related: {' '.join(rel_short)}"

        blocks.append(f"### {mid} {mtype} · {age} · {layer} · imp {bar} ({imp_f:.2f})")
        blocks.append(f"[modes: {modes} | links: {relation_count}]")
        blocks.append(content)
        if (m.get("metadata") or {}).get("via_memory_link"):
            src = str((m.get("metadata") or {}).get("linked_from") or "")[:8]
            kind = (m.get("metadata") or {}).get("link_kind") or "related"
            blocks.append(f"[linked from {src} via {kind}]")
        if rel_line:
            blocks.append(rel_line)
        blocks.append("")

    return "\n".join(blocks)


def memory_ids(memories: List[Dict[str, Any]]) -> List[str]:
    return [m.get("id", "") for m in memories if m.get("id")]


def make_related_lookup(
    graph_relations: List[Dict[str, Any]],
    *,
    min_strength: float = 0.0,
) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for r in graph_relations:
        try:
            strength = float(r.get("strength", 1.0) or 1.0)
        except Exception:
            strength = 1.0
        if strength < min_strength:
            continue
        a = r.get("from_id")
        b = r.get("to_id")
        if not a or not b or a == b:
            continue
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


__all__ = [
    "format_memories_brief",
    "format_memories_structured",
    "memory_ids",
    "make_related_lookup",
]
