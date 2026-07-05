"""Knowledge synthesis — LLM-powered topic synthesis stored as a memory."""

import logging
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import get_llm_client
from app.models.api import MemoryResult

log = logging.getLogger("nexus.memory.synthesis")

_SYNTH_PROMPT = """You are a knowledge synthesis engine. Given all stored memories about a topic, produce a comprehensive, structured synthesis document.

Topic: {topic}
Agent: {agent}

Memories ({count}):
{memories}

Produce a well-structured synthesis that:
1. Summarizes the key facts and knowledge
2. Identifies relationships and patterns
3. Notes any contradictions or uncertainties
4. Provides a clear knowledge base that can replace the individual memories

Format as clear prose, 3-6 paragraphs. Be specific and factual."""


async def synthesize_topic(
    db: AsyncSession,
    topic: str,
    agent_id: Optional[str] = None,
    limit: int = 30,
) -> Optional[str]:
    """Synthesize all memories on a topic into a single knowledge document."""
    from app.search.lexical import lexical_search
    from app.search.vector import vector_search
    from app.search.fusion import reciprocal_rank_fusion
    import asyncio

    vec, lex = await asyncio.gather(
        vector_search(db, topic, agent_id, limit=limit),
        lexical_search(db, topic, agent_id, limit=limit),
        return_exceptions=True,
    )

    lists = []
    if not isinstance(vec, Exception):
        lists.append(vec)
    if not isinstance(lex, Exception):
        lists.append(lex)

    if not lists:
        return None

    fused = reciprocal_rank_fusion(lists)[:limit]
    if not fused:
        return None

    llm = get_llm_client()
    if not llm:
        lines = [f"- [{m.memory_type}] {m.content}" for m in fused[:15]]
        return f"Knowledge summary for '{topic}':\n" + "\n".join(lines)

    mem_text = "\n".join(
        f"{i+1}. [{m.memory_type}] {m.content[:400]}" for i, m in enumerate(fused[:20])
    )

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _SYNTH_PROMPT.format(
                topic=topic, agent=agent_id or "all", count=min(len(fused), 20), memories=mem_text
            )}],
            max_tokens=settings.llm_synthesis_max_tokens,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning("Synthesis LLM failed: %s", e)
        lines = [f"- [{m.memory_type}] {m.content}" for m in fused[:10]]
        return f"Knowledge on '{topic}':\n" + "\n".join(lines)
