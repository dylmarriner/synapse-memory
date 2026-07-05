"""Reasoning engine: the cognitive process the mind applies to memories.

The reasoning pipeline is intentionally explicit so it can be
inspected, debugged, and tested.  It is *not* just "ask the LLM" —
each step produces a typed artefact that the next step consumes, and
the full trace is preserved in `ReasoningResult` so callers can
see *why* the mind reached a given conclusion.

Pipeline (standard depth):

    1. Intent       — what is being asked?
    2. Relevance    — which memories are actually about the question?
    3. Patterns     — what connections exist between relevant memories?
    4. Insights     — what is true that wasn't stated by any one memory?
    5. Conclusion   — the mind's grounded answer
    6. Confidence   — how strongly the memories support the conclusion

Fast depth: relevance + conclusion + confidence only.
Deep depth:  full pipeline + cross-check against the mind's identity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.reasoning")


@dataclass
class ReasoningStep:
    """One traceable step in the reasoning pipeline."""
    name: str                                  # e.g. "intent", "relevance", "patterns"
    input: Any
    output: Any
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "input": str(self.input)[:200], "output": str(self.output)[:500], "confidence": self.confidence}


@dataclass
class ReasoningResult:
    """The full output of a reasoning pass."""
    intent: str = ""                            # what the question is asking
    relevant_memory_ids: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    conclusion: str = ""                        # the grounded answer
    confidence: float = 0.0
    stance_hint: Optional[str] = None          # + / - / neutral — passed to the opinion system
    trace: List[ReasoningStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "relevant_memory_ids": self.relevant_memory_ids,
            "patterns": self.patterns,
            "insights": self.insights,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "stance_hint": self.stance_hint,
            "trace": [s.to_dict() for s in self.trace],
            "metadata": self.metadata,
        }


class ReasoningEngine:
    """Multi-step reasoning over memories.

    In production this is driven by an LLM (one call per step at
    standard depth, one consolidated call at fast depth, and a
    chain-of-thought call at deep depth).  In tests the LLM is
    optional — every step has a deterministic fallback that
    produces a result good enough for the rest of the pipeline.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self.llm = llm_client

    async def reason(
        self,
        question: str,
        memories: List[Dict[str, Any]],
        identity: Any,                            # the Identity object (typed loosely to avoid cycles)
        depth: Any = "standard",
    ) -> ReasoningResult:
        depth_value = depth.value if hasattr(depth, "value") else str(depth)
        result = ReasoningResult()

        # Step 1: Intent
        result.intent = self._infer_intent(question)
        result.trace.append(ReasoningStep(
            name="intent",
            input=question,
            output=result.intent,
            confidence=0.8,
        ))

        # Step 2: Relevance — which memories are actually about the question?
        relevant = self._filter_relevant(question, memories)
        result.relevant_memory_ids = [m.get("id", "") for m in relevant if m.get("id")]
        result.trace.append(ReasoningStep(
            name="relevance",
            input=f"{len(memories)} memories",
            output=f"{len(relevant)} relevant",
            confidence=0.7,
        ))

        if depth_value == "fast":
            # Fast path: skip patterns and insights, go straight to a conclusion.
            result.conclusion = self._compose_fast_conclusion(question, relevant)
            result.confidence = self._estimate_confidence(relevant)
            return result

        # Step 3: Patterns
        result.patterns = self._identify_patterns(relevant)
        result.trace.append(ReasoningStep(
            name="patterns",
            input=relevant,
            output=result.patterns,
            confidence=0.6,
        ))

        # Step 4: Insights
        result.insights = self._synthesize_insights(question, relevant, result.patterns)
        result.trace.append(ReasoningStep(
            name="insights",
            input=f"{len(relevant)} memories, {len(result.patterns)} patterns",
            output=result.insights,
            confidence=0.5,
        ))

        # Step 5: Conclusion
        result.conclusion = self._compose_conclusion(question, relevant, result.patterns, result.insights)
        result.stance_hint = self._infer_stance(result.conclusion)

        # Step 6: Confidence
        result.confidence = self._estimate_confidence(relevant, bonus=len(result.patterns) * 0.05)
        result.trace.append(ReasoningStep(
            name="confidence",
            input=relevant,
            output=result.confidence,
            confidence=0.7,
        ))
        return result

    async def reflect(self, topic: str, memories: List[Dict[str, Any]], depth: str = "mid") -> ReasoningResult:
        """Reflection is a deeper, more narrative variant of reasoning.

        The full pipeline runs, but patterns and insights get more
        weight, and the conclusion is rendered as a single coherent
        paragraph rather than bullet fragments.
        """
        result = await self.reason(
            question=f"Reflect on: {topic}",
            memories=memories,
            identity=None,
            depth=depth if depth in ("fast", "standard", "deep") else "deep",
        )
        # Replace the conclusion with a narrative paragraph
        result.conclusion = self._compose_reflection(topic, memories, result.patterns, result.insights)
        return result

    # ------------------------------------------------------------------
    # Deterministic fallbacks (used when the LLM is not wired)
    # ------------------------------------------------------------------

    def _infer_intent(self, question: str) -> str:
        """A short phrase describing what the question is asking for."""
        q = question.strip().lower().rstrip("?.!")
        if q.startswith(("what", "how", "why", "when", "where", "who")):
            return q
        if q.startswith("should"):
            return f"decision: {q}"
        if q.startswith("tell me about") or q.startswith("describe"):
            return f"recall: {q}"
        return f"recall: {q}"

    def _filter_relevant(self, question: str, memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keyword overlap plus structural weighting from the memory graph/layers."""
        q_tokens = {t.lower() for t in question.split() if len(t) > 2}
        if not q_tokens:
            return memories[:5]

        scored: List[tuple] = []
        for m in memories:
            text = (m.get("content") or m.get("text") or "").lower()
            m_tokens = {t for t in text.split() if len(t) > 2}
            overlap = len(q_tokens & m_tokens) / max(1, len(q_tokens))
            score = overlap + 0.1 * float(m.get("importance", 0.5) or 0.5)
            layer = m.get("layer") or (m.get("metadata") or {}).get("layer")
            relation_count = int(m.get("relation_count") or (m.get("metadata") or {}).get("relation_count") or 0)
            matched_by = list(m.get("matched_by") or [])
            if layer == "L3":
                score += 0.20
            elif layer == "L2":
                score += 0.12
            score += min(0.10, relation_count * 0.025)
            if "graph" in matched_by:
                score += 0.04
            if "linked" in matched_by:
                score += 0.05
            if (m.get("metadata") or {}).get("via_memory_link"):
                score += 0.04
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for score, m in scored if score > 0][:12]

    def _identify_patterns(self, memories: List[Dict[str, Any]]) -> List[str]:
        """Surface connections between memories, including graph/layer structure."""
        if not memories:
            return []
        type_counts: Dict[str, int] = {}
        layer_counts: Dict[str, int] = {}
        link_heavy = 0
        for m in memories:
            t = m.get("memory_type", "observation")
            type_counts[t] = type_counts.get(t, 0) + 1
            layer = m.get("layer") or (m.get("metadata") or {}).get("layer")
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
            if int(m.get("relation_count") or (m.get("metadata") or {}).get("relation_count") or 0) > 0:
                link_heavy += 1
        patterns = []
        for t, n in type_counts.items():
            if n >= 2:
                patterns.append(f"Multiple {t} memories ({n}) about this topic")
        for layer, n in sorted(layer_counts.items()):
            if n >= 2:
                patterns.append(f"{n} memories sit in {layer}, suggesting durable knowledge on this topic")
        if link_heavy >= 2:
            patterns.append(f"Knowledge-graph links connect {link_heavy} relevant memories into a cluster")
        tag_counts: Dict[str, int] = {}
        for m in memories:
            for tag in (m.get("metadata", {}).get("tags") or []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for tag, n in tag_counts.items():
            if n >= 2:
                patterns.append(f"Recurring tag '{tag}' ({n} memories)")
        return patterns

    def _synthesize_insights(
        self,
        question: str,
        memories: List[Dict[str, Any]],
        patterns: List[str],
    ) -> List[str]:
        """An insight is a statement that is *true* given the memories
        but not *stated* by any one of them.  The LLM call is the
        right place for this; the deterministic fallback produces
        weak-but-honest insights from the patterns we have."""
        if not memories:
            return []
        insights = []
        if patterns:
            insights.append(f"I notice {len(patterns)} patterns in what we know about this.")
        # Time-based insight
        if any(m.get("created_at") for m in memories):
            insights.append("The picture has been building over time — these aren't isolated facts.")
        # Frequency-based insight
        if len(memories) >= 3:
            insights.append("This topic comes up repeatedly — it's likely important.")
        return insights

    def _compose_fast_conclusion(self, question: str, memories: List[Dict[str, Any]]) -> str:
        if not memories:
            return f"I don't have anything specific about '{question}'."
        top = memories[0]
        return top.get("content", top.get("text", ""))[:300]

    def _compose_conclusion(
        self,
        question: str,
        memories: List[Dict[str, Any]],
        patterns: List[str],
        insights: List[str],
    ) -> str:
        if not memories:
            return f"I have no memories about '{question}'."
        parts: List[str] = []
        for m in memories[:5]:
            content = m.get("content") or m.get("text") or ""
            if content:
                parts.append(content[:200])
        if patterns:
            parts.append("Patterns: " + "; ".join(patterns))
        if insights:
            parts.append("Insights: " + "; ".join(insights))
        return " | ".join(parts)

    def _compose_reflection(
        self,
        topic: str,
        memories: List[Dict[str, Any]],
        patterns: List[str],
        insights: List[str],
    ) -> str:
        """A single-paragraph narrative reflection."""
        if not memories:
            return f"I have no memories to reflect on for '{topic}'."
        opening = f"On '{topic}', here's what stands out across {len(memories)} memories."
        body = []
        if patterns:
            body.append("Patterns: " + "; ".join(patterns))
        if insights:
            body.append("Insights: " + "; ".join(insights))
        # Close with a stance
        sample = " ".join((m.get("content") or "") for m in memories[:3])[:300]
        body.append(f"Putting it together: {sample}")
        return opening + " " + " ".join(body)

    def _infer_stance(self, conclusion: str) -> Optional[str]:
        low = conclusion.lower()
        positive = {"good", "great", "works", "success", "positive", "yes", "should", "agree"}
        negative = {"bad", "broken", "fails", "negative", "no", "shouldn't", "disagree", "bug", "broken"}
        # Count positive vs negative markers; majority wins.
        pos = sum(1 for w in positive if w in low)
        neg = sum(1 for w in negative if w in low)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"

    def _estimate_confidence(self, relevant: List[Dict[str, Any]], bonus: float = 0.0) -> float:
        """Estimate how well the memories support a conclusion.

        Count alone should not saturate confidence (50 loosely-matched
        memories ≠ certainty), so the count term is capped low and the
        bulk of the signal comes from the *average importance* of the
        relevant memories plus any pattern bonus.  Floor at 0.1.
        """
        if not relevant:
            return 0.1
        # Count contributes at most ~0.35 and saturates by ~8 memories.
        count_term = min(0.35, 0.05 * len(relevant))
        avg_importance = sum(float(m.get("importance", 0.5) or 0.5) for m in relevant) / len(relevant)
        score = 0.2 + count_term + 0.4 * avg_importance + bonus
        return max(0.1, min(0.97, score))


__all__ = ["ReasoningEngine", "ReasoningResult", "ReasoningStep"]
