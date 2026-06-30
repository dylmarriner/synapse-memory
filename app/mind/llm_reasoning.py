"""LLM-driven reasoning: multi-step pipeline for the Living Mind.

The previous version of this module made a single LLM call and used it
to enrich a deterministic result.  With a 7B model on local GPU, we
can do much more: the LLM is now the primary reasoner and the
deterministic pipeline becomes a guaranteed-correct fallback.

Pipeline (configurable per reasoning depth):

    extract   — pull claims/facts directly relevant from the memories.
                Skipped at FAST depth and when there are very few memories.
                Produces a list of {claim, evidence_ids} entries.
    reason    — synthesise a grounded answer with patterns + insights.
                Always called when an LLM is available.
    verify    — re-read the answer, flag unsupported claims, suggest
                corrections.  Only at DEEP depth.
    proactive — LLM-driven surfacing of context the user didn't ask
                about but should know.  Called separately by living_mind.

Each step is independent.  A failure in one step (LLM unavailable,
JSON parse error, timeout) falls through to the next step or to the
deterministic pipeline.  No step ever raises.

Caching: 5-minute LRU on (step, question_hash, memory_ids_hash,
extra_params) so repeated questions during testing don't re-run the
expensive GPU path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.mind.memory_format import format_memories_brief, format_memories_structured

log = logging.getLogger("nexus.mind.llm_reasoning")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# Each prompt returns JSON of a specific shape.  The `response_format`
# OpenAI parameter (Ollama supports it) forces strict JSON output.

SYSTEM_PROMPT_EXTRACT = """You are a memory claim-extractor.  Given a question and a set of memories, pull out the specific claims from the memories that are directly relevant to answering the question.

Rules:
- Only include claims that are directly relevant to the question.
- Each claim must cite at least one memory id as evidence.
- If a memory is irrelevant, skip it.
- If NO memories are relevant, return an empty claims list.
- Be precise: a claim is a single fact, not a paragraph.

Output JSON:
{
  "claims": [
    {"text": "specific claim", "evidence": ["memory-id-1"], "weight": 0.0-1.0}
  ]
}
"""

SYSTEM_PROMPT_REASON = """You are a Living Mind — a reasoning layer over a memory store.  Given a question and a set of relevant memories (with metadata: date, type, importance, related memories), produce a grounded answer.

Rules:
- Ground every claim in the memories you were given.  Quote memory ids in `evidence`.
- If the memories do not support an answer, say so plainly.
- Distinguish facts (memory-stated) from inferences (you reasoned) — put inferences in `insights`.
- Pay attention to memory age and importance: recent, high-importance memories outweigh old, low-importance ones.
- Be concise: 2-4 sentences for the answer.  Patterns and insights can be brief phrases.
- The "stance" describes the overall sentiment of the answer ("positive", "negative", "neutral").
- `confidence` is YOUR confidence the answer is correct given the memories (0.0-1.0).  Be honest: 0.4 if the memories are tangential, 0.8 if directly relevant, 0.95+ only if multiple high-importance memories agree.

Output JSON:
{
  "answer": "2-4 sentence grounded answer to the question",
  "evidence": ["memory-id-1", "memory-id-2"],
  "confidence": 0.0-1.0,
  "patterns": ["connection noticed across memories"],
  "insights": ["inference that no single memory states"],
  "stance": "positive|negative|neutral"
}
"""

SYSTEM_PROMPT_VERIFY = """You are a verification step.  Given a question, an LLM's draft answer, and the memories used, check the answer for unsupported claims and suggest corrections.

Rules:
- A claim is "supported" if at least one memory in the evidence set directly states it.
- A claim is "unsupported" if it goes beyond what the memories say (even if plausible).
- "corrected_answer" should be the same answer with unsupported claims softened ("X according to one memory" instead of "X is true") or removed.  If the answer is already well-grounded, return it unchanged.

Output JSON:
{
  "supported_claims": ["claims that are grounded in memories"],
  "unsupported_claims": ["claims that go beyond the memories"],
  "corrected_answer": "the verified answer",
  "confidence_adjustment": -0.2 to +0.2
}
"""

SYSTEM_PROMPT_PROACTIVE = """You are a proactive context-surfacer for a Living Mind.  Given a question, the memories the user already has, and the agent's recent activity, identify 0-3 pieces of context the user should know that they didn't ask about.

Rules:
- Only surface context that is RELEVANT to the question's topic — never random facts.
- Each item should be a single sentence with a clear "why this matters".
- The `evidence` field is the list of memory ids that support the proactive item.
- If no proactive context is warranted, return an empty list.

Output JSON:
{
  "proactive": [
    {"text": "context the user should know", "why": "short reason", "evidence": ["memory-id"]}
  ]
}
"""

SYSTEM_PROMPT_OPINION = """You are an opinion-formation step for a Living Mind.  Given a question, evidence memories, and the mind's current stance on the topic (if any), update or form a stance.

Rules:
- A stance is a directional attitude: positive, negative, or neutral.
- `strength` is 0.0-1.0 — how strongly the evidence supports the stance.
- The `reasoning` is a single sentence that cites the evidence.
- If the evidence is mixed or insufficient, return a neutral stance with low strength.
- This is a slow, careful opinion.  Don't infer from a single memory.

Output JSON:
{
  "stance": "positive|negative|neutral",
  "strength": 0.0-1.0,
  "reasoning": "one-sentence justification with evidence"
}
"""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LLMReasoningResult:
    """The output of one `reason` LLM call (or merged pipeline)."""
    answer: str = ""
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    patterns: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    stance: str = "neutral"
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # Pipeline metadata
    steps_run: List[str] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    claims: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ProactiveItem:
    """One proactive context item."""
    text: str
    why: str
    evidence: List[str] = field(default_factory=list)


@dataclass
class ProactiveResult:
    items: List[ProactiveItem] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class OpinionDraft:
    stance: str = "neutral"
    strength: float = 0.0
    reasoning: str = ""
    evidence: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ExtractedClaims:
    claims: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _LLMCache:
    """Tiny LRU + TTL cache for LLM call results.  Process-local, in-memory.

    Keyed by (step, question, top_memory_ids, params_hash).  Saves us
    re-running the 7b on the same question twice in a row during testing.
    """
    def __init__(self, max_size: int = 256, ttl_s: int = 300) -> None:
        self.max_size = max_size
        self.ttl_s = ttl_s
        self._data: Dict[str, Tuple[float, Any]] = {}

    @staticmethod
    def _key(step: str, question: str, memory_ids: List[str], params: Dict[str, Any]) -> str:
        mh = hashlib.sha1("|".join(sorted(memory_ids)).encode("utf-8")).hexdigest()[:12]
        ph = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
        qh = hashlib.sha1(question.encode("utf-8")).hexdigest()[:12]
        return f"{step}|{qh}|{mh}|{ph}"

    def get(self, step: str, question: str, memory_ids: List[str], params: Dict[str, Any]) -> Optional[Any]:
        k = self._key(step, question, memory_ids, params)
        v = self._data.get(k)
        if v is None:
            return None
        ts, val = v
        if time.time() - ts > self.ttl_s:
            self._data.pop(k, None)
            return None
        return val

    def set(self, step: str, question: str, memory_ids: List[str], params: Dict[str, Any], value: Any) -> None:
        k = self._key(step, question, memory_ids, params)
        # LRU-ish eviction
        if len(self._data) >= self.max_size:
            # Drop the oldest by timestamp
            oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
            self._data.pop(oldest, None)
        self._data[k] = (time.time(), value)

    def clear(self) -> None:
        self._data.clear()


# Module-level cache; safe because we only cache per-process
_cache = _LLMCache()


def clear_cache() -> None:
    """Reset the LLM call cache (used in tests)."""
    _cache.clear()


# ---------------------------------------------------------------------------
# LLM client helpers
# ---------------------------------------------------------------------------

# Server endpoints that don't support OpenAI's `response_format=json_object`.
# llama-server (llama.cpp HTTP), vLLM without xgrammar, and ollama without
# the right build will all 400 on it.  We detect by base URL host or by a
# per-process allow-list.
_NON_JSON_FORMAT_HOSTS = {
    "llama-server",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "host.docker.internal",
}


def _server_rejects_response_format(llm_client: Any) -> bool:
    """Return True if the LLM server is known to reject json_object format."""
    try:
        base = getattr(llm_client, "base_url", None) or ""
        # AsyncOpenAI stores base_url on .base_url
        host = base.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
        return host in _NON_JSON_FORMAT_HOSTS or host.endswith(".local")
    except Exception:
        return False


def _strip_think_blocks(text: str) -> str:
    """Remove Qwen3-style `<think>...</think>` blocks and return the
    visible answer.  Without this, the parser sees the thinking trace
    and thinks the model produced no answer."""
    if not text:
        return text
    cleaned = text
    # Strip closing </think> and everything inside <think>
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def is_llm_available(llm_client: Any) -> bool:
    """Return True if the LLM client is usable for reasoning."""
    if llm_client is None:
        return False
    return (
        hasattr(llm_client, "chat")
        or hasattr(llm_client, "generate")
        or hasattr(llm_client, "completions")
    )


async def _call_llm(
    llm_client: Any,
    system_prompt: str,
    user_msg: str,
    model: str,
    timeout: int,
    max_tokens: int,
    *,
    use_json_mode: bool = True,
) -> str:
    """Make the LLM call.  Supports the two shapes used in this repo:
    OpenAI-style (`chat.completions.create`) and the local LLM
    wrapper used in tests.
    """
    if hasattr(llm_client, "chat"):  # OpenAI client
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "timeout": timeout,
        }
        # `response_format=json_object` is an OpenAI-only feature.  Many
        # local servers (llama-server, vLLM without xgrammar) reject it
        # with 400.  We detect those servers by checking the base URL
        # and skip the format hint so the call succeeds and the parser
        # strips any non-JSON preamble.
        if use_json_mode and not _server_rejects_response_format(llm_client):
            kwargs["response_format"] = {"type": "json_object"}
        resp = await llm_client.chat.completions.create(**kwargs)
        return _strip_think_blocks(resp.choices[0].message.content or "")
    if hasattr(llm_client, "generate"):
        return await llm_client.generate(
            system=system_prompt,
            user=user_msg,
            max_tokens=max_tokens,
            temperature=0,
        )
    if hasattr(llm_client, "completions"):
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
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` or ``` ... ```
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        try:
            return json.loads(text)
        except Exception:
            return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Step: extract
# ---------------------------------------------------------------------------

async def llm_extract_claims(
    question: str,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    *,
    model: str,
    timeout: int = 45,
    max_tokens: int = 800,
    max_memories: int = 16,
) -> ExtractedClaims:
    """Pull the claims from `memories` that are directly relevant to `question`."""
    if not is_llm_available(llm_client) or not memories:
        return ExtractedClaims(error="llm_unavailable_or_no_memories")

    # Cache check
    params = {"model": model, "max_tokens": max_tokens, "step": "extract"}
    cached = _cache.get("extract", question, [m.get("id", "") for m in memories[:max_memories]], params)
    if cached is not None:
        return ExtractedClaims(**cached)

    mem_block = format_memories_structured(memories, max_items=max_memories, char_limit=240)
    user_msg = f"Question: {question}\n\nMemories:\n{mem_block}"

    try:
        response = await _call_llm(
            llm_client, SYSTEM_PROMPT_EXTRACT, user_msg, model, timeout, max_tokens,
        )
        parsed = _parse_json(response)
        claims = parsed.get("claims", [])
        # Sanitize
        clean: List[Dict[str, Any]] = []
        for c in claims:
            if not isinstance(c, dict):
                continue
            text = (c.get("text") or "").strip()
            evidence = c.get("evidence") or []
            if not text or not evidence:
                continue
            try:
                weight = float(c.get("weight", 0.5))
            except Exception:
                weight = 0.5
            weight = max(0.0, min(1.0, weight))
            clean.append({"text": text, "evidence": list(evidence), "weight": weight})
        result = ExtractedClaims(claims=clean)
        _cache.set("extract", question, [m.get("id", "") for m in memories[:max_memories]], params,
                   {"claims": result.claims, "error": None})
        return result
    except Exception as e:
        log.debug("llm_extract_claims failed: %s", e)
        return ExtractedClaims(error=str(e))


# ---------------------------------------------------------------------------
# Step: reason (the main call)
# ---------------------------------------------------------------------------

async def llm_reason(
    question: str,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    *,
    model: str,
    timeout: int = 60,
    max_tokens: int = 1000,
    max_memories: int = 16,
    depth: str = "standard",
    pre_extracted_claims: Optional[List[Dict[str, Any]]] = None,
) -> LLMReasoningResult:
    """Reason over `memories` and answer `question`.

    At `standard` and `deep` depths, memories are formatted with full
    metadata (date, importance, related).  At `fast` depth, a one-line
    brief is used for speed.
    """
    if not is_llm_available(llm_client):
        return LLMReasoningResult(error="llm_unavailable")

    if not memories and not pre_extracted_claims:
        return LLMReasoningResult(error="no_memories")

    mem_ids = [m.get("id", "") for m in memories[:max_memories]]
    params = {"model": model, "max_tokens": max_tokens, "depth": depth}
    cached = _cache.get("reason", question, mem_ids, params)
    if cached is not None:
        out = LLMReasoningResult(**cached)
        out.steps_run.append("reason:cached")
        return out

    if depth == "fast":
        mem_block = format_memories_brief(memories, max_items=max_memories, char_limit=140)
    else:
        mem_block = format_memories_structured(memories, max_items=max_memories, char_limit=300)

    user_parts = [f"Question: {question}"]
    if pre_extracted_claims:
        claim_lines = []
        for c in pre_extracted_claims:
            ev = ", ".join(c.get("evidence", []))
            claim_lines.append(f"- (weight {c.get('weight', 0.5):.2f}) {c['text']}  [ev: {ev}]")
        user_parts.append("Relevant claims (pre-extracted):\n" + "\n".join(claim_lines))
    user_parts.append("Memories:\n" + mem_block)
    user_msg = "\n\n".join(user_parts)

    try:
        response = await _call_llm(
            llm_client, SYSTEM_PROMPT_REASON, user_msg, model, timeout, max_tokens,
        )
        parsed = _parse_json(response)
        result = LLMReasoningResult(
            answer=(parsed.get("answer") or "").strip(),
            evidence=list(parsed.get("evidence", [])),
            confidence=_safe_float(parsed.get("confidence"), 0.0),
            patterns=list(parsed.get("patterns", [])),
            insights=list(parsed.get("insights", [])),
            stance=_norm_stance(parsed.get("stance")),
            raw=parsed,
            steps_run=["reason"],
        )
        if not result.answer:
            result.error = "empty_answer"
        # Cache the raw result (without steps_run) so re-calls are stable
        _cache.set("reason", question, mem_ids, params, {
            "answer": result.answer,
            "evidence": result.evidence,
            "confidence": result.confidence,
            "patterns": result.patterns,
            "insights": result.insights,
            "stance": result.stance,
            "raw": result.raw,
            "error": result.error,
            "verification": None,
            "claims": pre_extracted_claims or [],
        })
        return result
    except Exception as e:
        log.debug("llm_reason failed: %s", e)
        return LLMReasoningResult(error=str(e))


# ---------------------------------------------------------------------------
# Step: verify
# ---------------------------------------------------------------------------

async def llm_verify(
    question: str,
    draft: LLMReasoningResult,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    *,
    model: str,
    timeout: int = 45,
    max_tokens: int = 700,
    max_memories: int = 16,
) -> Dict[str, Any]:
    """Verify the draft answer against the memories.  Returns a dict with
    supported_claims, unsupported_claims, corrected_answer, confidence_adjustment.
    """
    if not is_llm_available(llm_client):
        return {"error": "llm_unavailable"}
    if not draft.answer:
        return {"error": "empty_draft"}

    mem_ids = [m.get("id", "") for m in memories[:max_memories]]
    params = {"model": model, "max_tokens": max_tokens}
    cached = _cache.get("verify", question, mem_ids, {**params, "draft": draft.answer})
    if cached is not None:
        return cached

    mem_block = format_memories_structured(memories, max_items=max_memories, char_limit=200)
    user_msg = (
        f"Question: {question}\n\n"
        f"Draft answer: {draft.answer}\n\n"
        f"Memories:\n{mem_block}"
    )
    try:
        response = await _call_llm(
            llm_client, SYSTEM_PROMPT_VERIFY, user_msg, model, timeout, max_tokens,
        )
        parsed = _parse_json(response)
        out = {
            "supported_claims": list(parsed.get("supported_claims", [])),
            "unsupported_claims": list(parsed.get("unsupported_claims", [])),
            "corrected_answer": (parsed.get("corrected_answer") or draft.answer).strip(),
            "confidence_adjustment": _safe_float(parsed.get("confidence_adjustment"), 0.0),
        }
        # Bound the adjustment
        out["confidence_adjustment"] = max(-0.2, min(0.2, out["confidence_adjustment"]))
        _cache.set("verify", question, mem_ids, {**params, "draft": draft.answer}, out)
        return out
    except Exception as e:
        log.debug("llm_verify failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Step: proactive
# ---------------------------------------------------------------------------

async def llm_proactive(
    question: str,
    memories: List[Dict[str, Any]],
    recent_activity: Optional[List[Dict[str, Any]]],
    llm_client: Any,
    *,
    model: str,
    timeout: int = 30,
    max_tokens: int = 500,
    max_memories: int = 12,
    max_items: int = 3,
) -> ProactiveResult:
    """LLM-driven proactive surfacing.  Returns 0-3 ProactiveItems."""
    if not is_llm_available(llm_client):
        return ProactiveResult(error="llm_unavailable")

    mem_ids = [m.get("id", "") for m in memories[:max_memories]]
    params = {"model": model, "max_tokens": max_tokens, "max_items": max_items}
    cached = _cache.get("proactive", question, mem_ids, params)
    if cached is not None:
        return ProactiveResult(items=[ProactiveItem(**i) for i in cached.get("items", [])])

    mem_block = format_memories_brief(memories, max_items=max_memories, char_limit=140)
    recent_block = ""
    if recent_activity:
        recent_lines = [f"- {a.get('text', '')}" for a in recent_activity[:5]]
        recent_block = "\n\nRecent activity:\n" + "\n".join(recent_lines)

    user_msg = f"Question: {question}\n\nRelevant memories:\n{mem_block}{recent_block}"

    try:
        response = await _call_llm(
            llm_client, SYSTEM_PROMPT_PROACTIVE, user_msg, model, timeout, max_tokens,
        )
        parsed = _parse_json(response)
        items_raw = parsed.get("proactive", []) or []
        items: List[ProactiveItem] = []
        for it in items_raw[:max_items]:
            if not isinstance(it, dict):
                continue
            text = (it.get("text") or "").strip()
            if not text:
                continue
            items.append(ProactiveItem(
                text=text,
                why=(it.get("why") or "").strip(),
                evidence=list(it.get("evidence", []) or []),
            ))
        result = ProactiveResult(items=items)
        _cache.set("proactive", question, mem_ids, params, {
            "items": [{"text": i.text, "why": i.why, "evidence": i.evidence} for i in items],
        })
        return result
    except Exception as e:
        log.debug("llm_proactive failed: %s", e)
        return ProactiveResult(error=str(e))


# ---------------------------------------------------------------------------
# Step: opinion
# ---------------------------------------------------------------------------

async def llm_opinion(
    question: str,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    *,
    model: str,
    current_stance: Optional[str] = None,
    current_strength: float = 0.0,
    timeout: int = 30,
    max_tokens: int = 400,
    max_memories: int = 8,
) -> OpinionDraft:
    """LLM-driven opinion formation."""
    if not is_llm_available(llm_client):
        return OpinionDraft(error="llm_unavailable")

    mem_ids = [m.get("id", "") for m in memories[:max_memories]]
    params = {"model": model, "max_tokens": max_tokens, "current": current_stance or ""}
    cached = _cache.get("opinion", question, mem_ids, params)
    if cached is not None:
        return OpinionDraft(
            stance=cached.get("stance", "neutral"),
            strength=cached.get("strength", 0.0),
            reasoning=cached.get("reasoning", ""),
            evidence=cached.get("evidence", []),
        )

    mem_block = format_memories_brief(memories, max_items=max_memories, char_limit=140)
    current_line = ""
    if current_stance:
        current_line = f"\n\nCurrent stance: {current_stance} (strength {current_strength:.2f})"
    user_msg = (
        f"Topic (from question): {question}\n\n"
        f"Evidence memories:\n{mem_block}{current_line}"
    )
    try:
        response = await _call_llm(
            llm_client, SYSTEM_PROMPT_OPINION, user_msg, model, timeout, max_tokens,
        )
        parsed = _parse_json(response)
        out = OpinionDraft(
            stance=_norm_stance(parsed.get("stance")),
            strength=_safe_float(parsed.get("strength"), 0.0),
            reasoning=(parsed.get("reasoning") or "").strip(),
            evidence=list(parsed.get("evidence", []) or []),
        )
        # Bound strength
        out.strength = max(0.0, min(1.0, out.strength))
        _cache.set("opinion", question, mem_ids, params, {
            "stance": out.stance, "strength": out.strength,
            "reasoning": out.reasoning, "evidence": out.evidence,
        })
        return out
    except Exception as e:
        log.debug("llm_opinion failed: %s", e)
        return OpinionDraft(error=str(e))


# ---------------------------------------------------------------------------
# Full multi-step pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    question: str,
    memories: List[Dict[str, Any]],
    llm_client: Any,
    llm_fallback: Any = None,
    *,
    primary_model: str,
    fallback_model: str,
    depth: str = "standard",
    enable_extract: bool = True,
    enable_verify: bool = True,
    enable_proactive_llm: bool = True,
    enable_opinion_llm: bool = True,
    max_memories: int = 16,
    related_lookup: Optional[Dict[str, List[str]]] = None,
    recent_activity: Optional[List[Dict[str, Any]]] = None,
    timeout_extract: int = 45,
    timeout_reason: int = 60,
    timeout_verify: int = 45,
    timeout_proactive: int = 30,
    timeout_opinion: int = 30,
) -> Dict[str, Any]:
    """Run the full LLM pipeline.  Returns a dict with:
        reason, proactive, opinion, claims, verification
    Each value is a Result dataclass; missing/errored steps fall through
    to the fallback (deterministic in the caller).
    """
    if not is_llm_available(llm_client):
        return {
            "reason": LLMReasoningResult(error="llm_unavailable"),
            "proactive": ProactiveResult(error="llm_unavailable"),
            "opinion": OpinionDraft(error="llm_unavailable"),
            "claims": ExtractedClaims(),
            "verification": None,
        }

    steps_run: List[str] = []
    claims_result: Optional[ExtractedClaims] = None
    pre_extracted_claims: Optional[List[Dict[str, Any]]] = None

    # ── extract ──
    if depth != "fast" and enable_extract and len(memories) >= 4:
        claims_result = await llm_extract_claims(
            question, memories, llm_client,
            model=primary_model, timeout=timeout_extract,
            max_memories=max_memories,
        )
        if not claims_result.error and claims_result.claims:
            pre_extracted_claims = claims_result.claims
            steps_run.append(f"extract({len(claims_result.claims)})")

    # ── reason ──
    reason_result = await llm_reason(
        question, memories, llm_client,
        model=primary_model, timeout=timeout_reason,
        max_memories=max_memories, depth=depth,
        pre_extracted_claims=pre_extracted_claims,
    )
    steps_run.append("reason:primary" if not reason_result.error else f"reason:err({reason_result.error})")
    reason_result.claims = pre_extracted_claims or []

    # ── fallback to secondary if primary failed ──
    if (not reason_result.answer or reason_result.error) and is_llm_available(llm_fallback):
        log.debug("primary LLM unproductive, trying fallback %s", fallback_model)
        fallback_result = await llm_reason(
            question, memories, llm_fallback,
            model=fallback_model, timeout=timeout_reason,
            max_memories=max_memories, depth=depth,
            pre_extracted_claims=pre_extracted_claims,
        )
        if fallback_result.answer and not fallback_result.error:
            reason_result = fallback_result
            steps_run.append("reason:fallback")

    # ── verify (DEEP only) ──
    verification: Optional[Dict[str, Any]] = None
    if (
        depth == "deep"
        and enable_verify
        and reason_result.answer
        and not reason_result.error
    ):
        verification = await llm_verify(
            question, reason_result, memories, llm_client,
            model=primary_model, timeout=timeout_verify,
            max_memories=max_memories,
        )
        if not verification.get("error"):
            steps_run.append("verify")
            # Apply the correction
            if verification.get("corrected_answer"):
                reason_result.answer = verification["corrected_answer"]
            # Apply confidence adjustment
            adj = verification.get("confidence_adjustment", 0.0) or 0.0
            reason_result.confidence = max(0.0, min(1.0, reason_result.confidence + adj))
            reason_result.verification = verification

    # ── proactive ──
    if depth != "fast" and enable_proactive_llm:
        proactive_result = await llm_proactive(
            question, memories, recent_activity, llm_client,
            model=primary_model, timeout=timeout_proactive,
            max_memories=max_memories,
        )
        if proactive_result.error and is_llm_available(llm_fallback):
            # try fallback
            log.debug("primary proactive failed, trying fallback")
            proactive_result = await llm_proactive(
                question, memories, recent_activity, llm_fallback,
                model=fallback_model, timeout=timeout_proactive,
                max_memories=max_memories,
            )
        if not proactive_result.error:
            steps_run.append("proactive")
    else:
        proactive_result = ProactiveResult(error="disabled")

    # ── opinion ──
    if enable_opinion_llm:
        opinion_result = await llm_opinion(
            question, memories, llm_client,
            model=primary_model, timeout=timeout_opinion,
            max_memories=min(max_memories, 8),
        )
        if opinion_result.error and is_llm_available(llm_fallback):
            log.debug("primary opinion failed, trying fallback")
            opinion_result = await llm_opinion(
                question, memories, llm_fallback,
                model=fallback_model, timeout=timeout_opinion,
                max_memories=min(max_memories, 8),
            )
        if not opinion_result.error:
            steps_run.append("opinion")
    else:
        opinion_result = OpinionDraft(error="disabled")

    reason_result.steps_run = steps_run
    return {
        "reason": reason_result,
        "proactive": proactive_result,
        "opinion": opinion_result,
        "claims": claims_result or ExtractedClaims(),
        "verification": verification,
    }


# ---------------------------------------------------------------------------
# Enrichment (keeps the old public API for backward compat)
# ---------------------------------------------------------------------------

def enrich_reasoning_result(
    deterministic_result: Any,
    llm_result: LLMReasoningResult,
) -> Any:
    """Merge the LLM's richer output into the deterministic result.

    The deterministic pipeline gives us a guaranteed-correct conclusion
    (built from the top-k memories).  The LLM gives us richer patterns,
    insights, and a higher-quality answer.  We take the LLM's `answer`,
    `patterns`, `insights`, `evidence`, `stance`, and `confidence` when
    the LLM call succeeded, and keep the deterministic fallback otherwise.
    """
    if llm_result.error or not llm_result.answer:
        return deterministic_result

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
    # Append the LLM step to the trace
    from app.mind.reasoning import ReasoningStep
    deterministic_result.trace.append(ReasoningStep(
        name="llm_reason",
        input=f"question={deterministic_result.intent!r}",
        output=llm_result.answer[:300],
        confidence=llm_result.confidence,
    ))
    if llm_result.steps_run:
        deterministic_result.trace.append(ReasoningStep(
            name="llm_pipeline",
            input="",
            output=",".join(llm_result.steps_run),
            confidence=llm_result.confidence,
        ))
    return deterministic_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_stance(value: Any) -> str:
    s = str(value or "").lower().strip()
    if s.startswith("pos"):
        return "positive"
    if s.startswith("neg"):
        return "negative"
    return "neutral"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


__all__ = [
    # Main result types
    "LLMReasoningResult",
    "ProactiveItem",
    "ProactiveResult",
    "OpinionDraft",
    "ExtractedClaims",
    # Step functions
    "llm_extract_claims",
    "llm_reason",
    "llm_verify",
    "llm_proactive",
    "llm_opinion",
    # Pipeline
    "run_pipeline",
    # Helpers
    "is_llm_available",
    "enrich_reasoning_result",
    "clear_cache",
]
