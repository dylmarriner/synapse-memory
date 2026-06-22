"""Optional reranker layer applied after RRF fusion.

Providers:
  none  — pass-through, returns results unchanged (default).
  llm   — uses the configured LLM to score top-K candidates against the query.

Enable with:
  RERANKER_ENABLED=true
  RERANKER_PROVIDER=llm   # or none
  RERANK_TOP_K=30
"""

import asyncio
import json
import logging
from typing import Optional

from app.config import settings
from app.models.api import MemoryResult

log = logging.getLogger("nexus.search.rerank")

_RERANK_PROMPT = """\
You are a relevance judge. Score each candidate memory 0.0-1.0 for how well it answers the query.
Return JSON only: {{"scores": [<float>, ...]}} with one score per candidate in the same order.

Query: {query}

Candidates:
{candidates}
"""


async def rerank(
    query: str,
    results: list[MemoryResult],
    limit: int,
    provider: Optional[str] = None,
    top_k: Optional[int] = None,
) -> list[MemoryResult]:
    """Rerank `results` and return at most `limit` items.

    When reranking is disabled or the provider is 'none', this is a no-op
    that returns results[:limit].
    """
    if not settings.reranker_enabled:
        return results[:limit]

    effective_provider = provider or settings.reranker_provider
    effective_top_k = top_k or settings.rerank_top_k

    candidates = results[:effective_top_k]
    if not candidates:
        return []

    if effective_provider == "llm":
        return await _llm_rerank(query, candidates, limit)

    return candidates[:limit]


async def _llm_rerank(query: str, candidates: list[MemoryResult], limit: int) -> list[MemoryResult]:
    """Score candidates with an LLM relevance call, then sort and return top-limit."""
    from app.llm import call_llm

    numbered = "\n".join(
        f"{i + 1}. [{r.memory_type}] {r.content[:300]}"
        for i, r in enumerate(candidates)
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=numbered)

    try:
        raw = await asyncio.wait_for(call_llm(prompt, max_tokens=256), timeout=8.0)
        data = json.loads(raw)
        scores = data.get("scores", [])
        if len(scores) != len(candidates):
            log.warning("Reranker score count mismatch: expected %d got %d", len(candidates), len(scores))
            return candidates[:limit]
        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: float(x[1]),
            reverse=True,
        )
        reranked = [r for r, _ in ranked[:limit]]
        # Overwrite score with reranker score for transparency
        for (r, s) in ranked[:limit]:
            r.score = float(s)
        return reranked
    except Exception as e:
        log.warning("LLM rerank failed, falling back to RRF order: %s", e)
        return candidates[:limit]
