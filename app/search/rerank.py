"""Optional reranker layer applied after RRF fusion.

Providers:
  none  — pass-through, returns results unchanged (default).
  llm   — uses the configured LLM to score top-K candidates against the query.
  local — uses a local sentence-transformers CrossEncoder (10-50ms, no API cost).

Enable with:
  RERANKER_ENABLED=true
  RERANKER_PROVIDER=local        # or llm / none
  RERANKER_LOCAL_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2
  RERANK_TOP_K=30
"""

import asyncio
import json
import logging
from typing import Optional, TYPE_CHECKING

from app.config import settings
from app.models.api import MemoryResult

log = logging.getLogger("nexus.search.rerank")

_cross_encoder = None


def _get_cross_encoder(model_name: str):
    global _cross_encoder
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder(model_name)
            log.info("Local cross-encoder loaded: %s", model_name)
        except ImportError:
            log.warning("sentence-transformers not installed; falling back to RRF order")
    return _cross_encoder


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

    if effective_provider == "local":
        return await _local_rerank(query, candidates, limit)

    return candidates[:limit]


async def _llm_rerank(query: str, candidates: list[MemoryResult], limit: int) -> list[MemoryResult]:
    """Score candidates with an LLM relevance call, then sort and return top-limit."""
    from app.llm import llm_complete

    numbered = "\n".join(
        f"{i + 1}. [{r.memory_type}] {r.content[:300]}"
        for i, r in enumerate(candidates)
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=numbered)

    try:
        raw = await asyncio.wait_for(llm_complete(prompt, max_tokens=256), timeout=8.0)
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


async def _local_rerank(query: str, candidates: list[MemoryResult], limit: int) -> list[MemoryResult]:
    """Score candidates with a local cross-encoder, then sort and return top-limit."""
    model = _get_cross_encoder(settings.reranker_local_model)
    if model is None:
        return candidates[:limit]

    pairs = [(query, r.content[:512]) for r in candidates]
    loop = asyncio.get_event_loop()
    try:
        scores = await asyncio.wait_for(
            loop.run_in_executor(None, model.predict, pairs),
            timeout=10.0,
        )
        ranked = sorted(zip(candidates, scores), key=lambda x: float(x[1]), reverse=True)
        for r, s in ranked[:limit]:
            r.score = float(s)
        return [r for r, _ in ranked[:limit]]
    except Exception as e:
        log.warning("Local rerank failed, falling back to RRF order: %s", e)
        return candidates[:limit]
