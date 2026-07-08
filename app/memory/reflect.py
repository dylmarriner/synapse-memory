"""Deterministic reflection synthesis over recalled memories."""

import logging
from typing import List, Optional

from app.models.api import MemoryResult, MemoryReflectRequest, MemoryReflectResponse

log = logging.getLogger("nexus.memory.reflect")


async def reflect(
    req: MemoryReflectRequest,
    recalled: List[MemoryResult],
) -> MemoryReflectResponse:
    if not recalled:
        return MemoryReflectResponse(reflection="No relevant memories found.", based_on=[])
    by_type: dict[str, int] = {}
    seen_contents: set[str] = set()
    top_points: list[str] = []
    for memory in recalled:
        by_type[memory.memory_type] = by_type.get(memory.memory_type, 0) + 1
        content = (memory.content or "").strip()
        if not content:
            continue
        key = content.lower()
        if key in seen_contents:
            continue
        seen_contents.add(key)
        top_points.append(f"- [{memory.memory_type}] {content[:240]}")
        if len(top_points) >= 8:
            break

    contradictions = [
        m for m in recalled
        if (m.contradicted_count or 0) > 0 or (m.metadata or {}).get("failure")
    ]
    lines = [f"Reflection for: {req.query}"]
    if req.context:
        lines.append(f"Context: {req.context[:240]}")
    lines.append(f"Evidence count: {len(recalled)}")
    if by_type:
        mix = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
        lines.append(f"Memory mix: {mix}")
    if top_points:
        lines.append("Key evidence:")
        lines.extend(top_points)
    if contradictions:
        lines.append(f"Conflicts or cautions: {len(contradictions)} memories are marked contradicted or failure-related.")
    lines.append("Conclusion: use the key evidence above directly; this endpoint now returns deterministic synthesis only.")
    return MemoryReflectResponse(reflection="\n".join(lines), based_on=recalled[:10])
