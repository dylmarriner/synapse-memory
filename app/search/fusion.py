"""Reciprocal Rank Fusion — merge ranked result lists with confidence-aware re-ranking."""

from typing import Optional, List, Dict
from app.models.api import MemoryResult


def _trust_multiplier(r: MemoryResult) -> float:
    """Boost/demote based on confirmed_count vs contradicted_count."""
    confirmed = r.confirmed_count or 0
    contradicted = r.contradicted_count or 0
    if confirmed + contradicted == 0:
        return 1.0
    trust = confirmed / (confirmed + contradicted)
    if contradicted > confirmed:
        return 0.5 + trust * 0.3
    return 1.0 + min(trust * 0.3, 0.3)


def _multi_mode_bonus(mode_count: int) -> float:
    """Memories found by multiple search modes are more relevant."""
    if mode_count >= 3:
        return 1.25
    if mode_count >= 2:
        return 1.12
    return 1.0


def reciprocal_rank_fusion(
    result_lists: List[List[MemoryResult]],
    k: int = 60,
    mode_weights: Optional[Dict[str, float]] = None,
) -> List[MemoryResult]:
    """
    RRF score = Σ weight_i / (k + rank_i(d))
    Then re-ranked with trust scoring + multi-mode bonus + importance weight.
    """
    weights: Dict[str, float] = mode_weights or {
        "vector": 1.1,
        "lexical": 1.0,
        "graph": 0.9,
        "temporal": 0.8,
    }

    scores: Dict[str, float] = {}
    best: Dict[str, MemoryResult] = {}
    modes: Dict[str, List[str]] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            mem_id = result.id
            mode_w = max((weights.get(m, 1.0) for m in result.matched_by), default=1.0)
            scores[mem_id] = scores.get(mem_id, 0.0) + mode_w / (k + rank + 1)

            if mem_id not in best or result.score > best[mem_id].score:
                best[mem_id] = result

            existing = modes.setdefault(mem_id, [])
            for m in result.matched_by:
                if m not in existing:
                    existing.append(m)

    fused = []
    for mem_id, result in best.items():
        r = result.model_copy()
        rrf_score = scores[mem_id]
        trust = _trust_multiplier(r)
        multi = _multi_mode_bonus(len(modes[mem_id]))
        importance_boost = 1.0 + r.importance * 0.15
        r.score = round(rrf_score * trust * multi * importance_boost, 6)
        r.matched_by = modes[mem_id]
        fused.append(r)

    fused.sort(key=lambda r: r.score, reverse=True)
    return fused
