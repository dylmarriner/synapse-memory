"""LLM-driven reflection synthesis over recalled memories."""

import logging
from typing import List, Optional

from app.models.api import MemoryResult, MemoryReflectRequest, MemoryReflectResponse
from app.llm import get_llm_client
from app.config import settings

log = logging.getLogger("nexus.memory.reflect")

_PROMPT = """You are a memory synthesis engine. Given a question and a set of retrieved memories, produce a structured reflection.

Question: {query}{ctx}

Retrieved memories ({count}):
{memories}

Synthesize a clear, insightful reflection that:
1. Directly answers the question from the evidence
2. Identifies patterns or recurring themes
3. Notes contradictions or gaps
4. Draws actionable conclusions

Be concise and factual."""


async def reflect(
    req: MemoryReflectRequest,
    recalled: List[MemoryResult],
) -> MemoryReflectResponse:
    if not recalled:
        return MemoryReflectResponse(reflection="No relevant memories found.", based_on=[])

    client = get_llm_client()
    if client is None:
        summary = "\n".join(f"- [{m.memory_type}] {m.content}" for m in recalled[:10])
        return MemoryReflectResponse(
            reflection=f"Memory summary ({len(recalled)} results):\n{summary}",
            based_on=recalled[:10],
        )

    cap = settings.llm_reflect_max_tokens
    depth_tokens = {"low": min(120, cap), "mid": min(300, cap), "high": min(600, cap)}
    max_tokens = depth_tokens.get(req.depth, 400)

    mem_text = "\n".join(
        f"{i+1}. [{m.memory_type}] {m.content[:300]}" for i, m in enumerate(recalled[:10])
    )
    ctx_str = f"\nContext: {req.context}" if req.context else ""

    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _PROMPT.format(
                query=req.query, ctx=ctx_str, count=len(recalled), memories=mem_text
            )}],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        text_out = resp.choices[0].message.content.strip()
        return MemoryReflectResponse(reflection=text_out, based_on=recalled[:10])
    except Exception as e:
        log.warning("Reflect LLM call failed: %s", e)
        fallback = "\n".join(f"- {m.content[:200]}" for m in recalled[:5])
        return MemoryReflectResponse(
            reflection=f"Top {min(5, len(recalled))} memories:\n{fallback}",
            based_on=recalled[:5],
        )
