"""LLM-driven reasoning: high-quality reasoning when an LLM is available.

The `ReasoningEngine` in `reasoning.py` is a deterministic fallback —
fast, side-effect free, but limited.  This module adds an LLM-driven
path that produces *richer* reasoning at the cost of one model call
per step.

The LLM is treated as a pluggable dependency.  In production we use
the existing `app.llm.get_llm_client()` to obtain the client.  In
tests and embedded use, no LLM is needed — the deterministic
pipeline produces a good-enough result.

The LLM is used in three places, in order of cost vs quality:

  1. **Patterns & insights** (one call per think).  High quality,
     but you could skip this in fast mode.
  2. **The conclusion** (one call per think).  The most important
     part — the user-visible answer.  Skipping this and using the
     deterministic conclusion is the biggest quality loss.
  3. **The composition** (no call — deterministic).  This is just
     formatting; the LLM doesn't help here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.llm_reasoning")

# The system prompt used for the LLM reasoning step.  It is short on
# purpose — the LLM is given the recalled memories as raw material and
# asked to synthesise a grounded answer.
_LLM_SYSTEM_PROMPT = """You are a Living Mind — a reasoning layer over a memory store.
Given a question and a set of relevant memories, produce a grounded
answer.

Rules:
- Ground every claim in the memories you were given.
- Quote memory ids in `evidence` so the answer can be traced.
- If the memories do not support an answer, say so plainly.
- Distinguish facts (memory-stated) from inferences (you reasoned).
- Be concise: 2-4 sentences is usually enough.
- Write a REAL answer in your own words — never copy the field
  descriptions from the schema below.

Respond with ONLY a JSON object of this shape (values are descriptions
of what to put, not literal text to copy):
{{
  "answer": <2-4 sentence grounded answer to the question>,
  "evidence": [<ids of memories you used>],
  "confidence": <0.0-1.0 how well the memories support your answer>,
  "patterns": [<connections you noticed across memories>],
  "insights": [<things true given the memories but not stated by any one>],
  "stance": <"positive" | "negative" | "neutral">
}}"""


@dataclass
class LLMReasoningResult:
    """The output of one LLM reasoning call."""
    answer: str = ""
    evidence: List[str] = None      # type: ignore[assignment]
    confidence: float = 0.0
    patterns: List[str] = None      # type: ignore[assignment]
    insights: List[str] = None      # type: ignore[assignment]
    stance: str = "neutral"
    raw: Dict[str, Any] = None      # type: ignore[assignment]
    error: Optional[str] = None

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []
        if self.patterns is None:
            self.patterns = []
        if self.insights is None:
            self.insights = []
        if self.raw is None:
            self.raw = {}


def is_llm_available(llm_client: Any) -> bool:
    """Return True if the LLM client is usable for reasoning."""
    if llm_client is None:
        return False
    return hasattr(llm_client, "chat") or hasattr(llm_client, "generate") or hasattr(llm_client, "completions")


async def llm_reason(
    question: str,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    *,
    model: str = "qwen2.5:3b",
    timeout: int = 30,
    max_tokens: int = 800,
) -> LLMReasoningResult:
    """Call the LLM to reason over `memories` and answer `question`.

    Returns an `LLMReasoningResult` with the parsed JSON fields.  If
    anything goes wrong (LLM unavailable, parse error, timeout), the
    result's `error` is set and the safe defaults are used so the
    caller can fall back gracefully.
    """
    if not is_llm_available(llm_client):
        return LLMReasoningResult(error="llm_unavailable")

    # Build the user message with the memories
    mem_lines = []
    for m in memories[:16]:
        mid = m.get("id", "")
        content = (m.get("content") or "")[:300]
        mem_lines.append(f"- id={mid}  text={content}")
    user_msg = (
        f"Question: {question}\n\n"
        f"Relevant memories:\n" + "\n".join(mem_lines) if mem_lines
        else f"Question: {question}\n\nNo memories found."
    )

    try:
        response = await _call_llm(llm_client, _LLM_SYSTEM_PROMPT, user_msg, model, timeout, max_tokens)
        parsed = _parse_json(response)
        return LLMReasoningResult(
            answer=parsed.get("answer", ""),
            evidence=parsed.get("evidence", []),
            confidence=float(parsed.get("confidence", 0) or 0),
            patterns=parsed.get("patterns", []),
            insights=parsed.get("insights", []),
            stance=parsed.get("stance", "neutral"),
            raw=parsed,
        )
    except Exception as e:
        log.debug("llm_reason failed: %s", e)
        return LLMReasoningResult(error=str(e))


async def _call_llm(
    llm_client: Any,
    system_prompt: str,
    user_msg: str,
    model: str,
    timeout: int,
    max_tokens: int,
) -> str:
    """Make the LLM call.  Supports the two shapes used in this repo:
    OpenAI-style (`chat.completions.create`) and the local LLM
    wrapper used in tests.
    """
    if hasattr(llm_client, "chat"):  # OpenAI client
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
            temperature=0,
            timeout=timeout,
        )
        return resp.choices[0].message.content or ""
    if hasattr(llm_client, "generate"):
        # Legacy local wrapper
        return await llm_client.generate(
            system=system_prompt,
            user=user_msg,
            max_tokens=max_tokens,
            temperature=0,
        )
    if hasattr(llm_client, "completions"):
        # Newer OpenAI shape
        resp = await llm_client.completions.create(
            model=model,
            prompt=system_prompt + "\n\n" + user_msg,
            max_tokens=max_tokens,
            temperature=0,
            timeout=timeout,
        )
        return resp.choices[0].text or ""
    raise RuntimeError(f"unknown LLM client shape: {type(llm_client)}")


def _parse_json(text: str) -> Dict[str, Any]:
    """Extract a JSON object from a possibly-noisy LLM response."""
    if not text:
        return {}
    # Strip markdown fences
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    # Find the first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        # Fall back to direct parse
        try:
            return json.loads(text)
        except Exception:
            return {"answer": text, "confidence": 0.3}
    return json.loads(text[start:end + 1])


def enrich_reasoning_result(
    deterministic_result: Any,
    llm_result: LLMReasoningResult,
) -> Any:
    """Merge the LLM's richer output into the deterministic result.

    The deterministic pipeline gives us a guaranteed-correct
    conclusion (built from the top-k memories).  The LLM gives us
    richer patterns, insights, and a higher-quality answer.  We
    take the LLM's `answer`, `patterns`, `insights`, `evidence`,
    `stance`, and `confidence` when the LLM call succeeded, and
    keep the deterministic fallback otherwise.

    The function returns the same `ReasoningResult` shape so the
    caller doesn't need to know which path produced it.
    """
    if llm_result.error or not llm_result.answer:
        return deterministic_result

    # Replace the fields that the LLM improves
    deterministic_result.conclusion = llm_result.answer
    deterministic_result.confidence = max(
        float(deterministic_result.confidence or 0),
        llm_result.confidence,
    )
    if llm_result.patterns:
        deterministic_result.patterns = list(llm_result.patterns)
    if llm_result.insights:
        deterministic_result.insights = list(llm_result.insights)
    if llm_result.stance:
        deterministic_result.stance_hint = llm_result.stance
    # Append the LLM step to the trace so the audit log shows it
    from app.mind.reasoning import ReasoningStep
    deterministic_result.trace.append(ReasoningStep(
        name="llm_reason",
        input=f"question={deterministic_result.intent!r}",
        output=llm_result.answer[:300],
        confidence=llm_result.confidence,
    ))
    return deterministic_result


__all__ = [
    "LLMReasoningResult",
    "is_llm_available",
    "llm_reason",
    "enrich_reasoning_result",
]
