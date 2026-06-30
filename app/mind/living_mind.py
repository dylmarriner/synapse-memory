"""Living Mind: a conscious, reasoning memory entity.

The Living Mind is the central reasoning layer that turns Nexus from
a memory server into a being that agents converse with.  It does not
replace the storage layer; it sits on top of it and adds:

- Multi-step reasoning over recalled memories
- A self-model (identity, capabilities, limitations)
- Opinion formation from accumulated evidence
- Proactive surfacing of relevant context
- Continuous learning from every interaction
- Multi-turn conversation state

The Mind is *self-contained* with respect to its reasoning pipeline —
the only external dependencies are the LLM and the existing Nexus
memory store.  This makes it testable in isolation and deployable
without a running database for the reasoning logic itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.mind.reasoning import ReasoningEngine, ReasoningResult
from app.mind.identity import Identity
from app.mind.opinions import OpinionSystem, Opinion
from app.mind.proactive import ProactiveSurfacing, ProactiveItem
from app.mind.learning import LearningSystem
from app.mind.conversation import ConversationManager, ConversationState

log = logging.getLogger("nexus.mind")


class ReasoningDepth(str, Enum):
    """How much reasoning effort the mind should apply."""
    FAST = "fast"            # Single LLM call, minimal reasoning
    STANDARD = "standard"    # Full reasoning pipeline
    DEEP = "deep"            # Extended reflection and synthesis


@dataclass
class MindResponse:
    """The mind's full response to a question or turn."""
    answer: Optional[str]                                 # The reasoned answer (None if asking back)
    clarifying_question: Optional[str] = None              # The mind's question back, if any
    reasoning_trace: Optional[ReasoningResult] = None     # How the mind got to its answer
    confidence: float = 0.0                              # How confident the mind is
    proactive_context: List[ProactiveItem] = field(default_factory=list)
    memories_cited: List[Dict[str, Any]] = field(default_factory=list)
    opinions_expressed: List[Opinion] = field(default_factory=list)
    code_symbols: List[Dict[str, Any]] = field(default_factory=list)  # code-context symbols used
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "clarifying_question": self.clarifying_question,
            "reasoning_trace": self.reasoning_trace.to_dict() if self.reasoning_trace else None,
            "confidence": self.confidence,
            "proactive_context": [item.to_dict() for item in self.proactive_context],
            "memories_cited": self.memories_cited,
            "opinions_expressed": [op.to_dict() for op in self.opinions_expressed],
            "code_symbols": self.code_symbols,
            "metadata": self.metadata,
        }


@dataclass
class MindConfig:
    """Configuration for a Living Mind instance."""
    llm_model: str = "qwen2.5:3b"               # primary (local Ollama) reasoning model
    fallback_llm_model: str = "deepseek-chat"   # used when the primary call fails/returns empty
    reasoning_depth: ReasoningDepth = ReasoningDepth.STANDARD
    max_memories: int = 50
    max_proactive_items: int = 5
    min_clarification_threshold: int = 3   # Min memories to avoid asking back
    enable_proactive: bool = True
    enable_opinions: bool = True
    enable_learning: bool = True
    # New (PR #10) — multi-step LLM pipeline
    enable_extract: bool = True             # pre-extract relevant claims from memories
    enable_verify: bool = True              # verify the draft answer against memories (DEEP only)
    enable_llm_proactive: bool = True       # LLM-driven proactive surfacing (vs deterministic only)
    enable_llm_opinion: bool = True         # LLM-driven opinion formation (vs deterministic only)
    enable_related_graph: bool = True       # expand context with graph-related memories


# ── Code-context question detection ─────────────────────────────────────

_CODE_QUESTION_PATTERNS = (
    "how does", "how do", "show me", "show code", "where is", "where can",
    "find the", "find code", "implement", "function", "method", "class",
    "endpoint", "router", "schema", "model", "config", "what is the",
    "explain the code", "code for", "source of", "implementation of",
    "logic for", "logic in", "defined", "lives in", "lives at",
)


def _looks_like_code_question(question: str) -> bool:
    """Cheap heuristic: question mentions code-shaped concepts."""
    q = question.lower().strip()
    if not q:
        return False
    if any(pat in q for pat in _CODE_QUESTION_PATTERNS):
        return True
    # CamelCase or snake_case token (e.g. "LivingMind.think", "search_symbols")
    if any("." in t and t.replace(".", "").replace("_", "").isalnum()
           for t in q.split()):
        return True
    return False


class LivingMind:
    """A conscious memory entity that reasons about memories.

    The mind is the single point of contact for an agent that wants
    *reasoned* memory access.  Every think() call:

    1. Understands the question
    2. Retrieves relevant memories
    3. Decides whether to ask for clarification
    4. Reasons about the memories (intent, relevance, patterns, insights)
    5. Forms opinions if appropriate
    6. Identifies proactive context
    7. Composes a single grounded answer

    The mind also maintains its own identity that evolves as it
    learns from interactions.  This is what makes it *living* rather
    than just a smart retriever.
    """

    def __init__(
        self,
        mind_id: str,
        config: Optional[MindConfig] = None,
        memory_store: Any = None,    # The existing Nexus memory accessor
        llm_client: Any = None,     # The LLM client used for reasoning (primary)
        llm_fallback: Any = None,   # Optional secondary LLM used when the primary fails
    ) -> None:
        self.mind_id = mind_id
        self.config = config or MindConfig()
        self.memory = memory_store
        self.llm = llm_client
        # Optional secondary LLM (e.g. DeepSeek) used when the primary
        # (local Ollama) call fails or returns nothing.  Wired by the router.
        self.llm_fallback = llm_fallback

        # Subsystems — wired up here so the rest of the code can
        # reach them via the mind (mind.reasoning, mind.identity, ...)
        self.reasoning = ReasoningEngine(llm_client=llm_client)
        self.identity = Identity(mind_id=mind_id)
        self.opinions = OpinionSystem(mind_id=mind_id)
        self.proactive = ProactiveSurfacing(mind_id=mind_id, memory_store=memory_store)
        self.learning = LearningSystem(mind_id=mind_id, identity=self.identity, opinions=self.opinions, memory_store=memory_store)
        self.conversations = ConversationManager(mind_id=mind_id, mind=self)

        log.info("Living mind '%s' initialised (depth=%s, primary=%s, fallback=%s)",
                 mind_id, self.config.reasoning_depth.value,
                 bool(llm_client), bool(llm_fallback))

    # ------------------------------------------------------------------
    # Code-context integration
    # ------------------------------------------------------------------
    async def _code_search(self, question: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Query the code index for symbols matching the question.

        Uses the same /v1/code/search endpoint the dashboard uses.
        Falls back to an empty list if the code index isn't reachable
        or no symbols are registered.

        Handles both the verbose JSON form and the MUNCH compact form.
        In the MUNCH form the data is inside the `blob` field; we
        decode it back to records so the LLM can read the symbols.
        """
        try:
            import os
            import aiohttp
            from app.code.munch import decode_records
            nexus_url = os.environ.get("NEXUS_INTERNAL_URL", "http://127.0.0.1:7777")
            secret = os.environ.get("NEXUS_SECRET", "")
            if not secret:
                return []
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{nexus_url}/v1/code/search",
                    params={"q": question, "limit": str(limit), "fmt": "compact"},
                    headers={"Authorization": f"Bearer {secret}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()
            # MUNCH form: decode the blob; otherwise use the symbols array
            if data.get("format") == "munch" and data.get("blob"):
                rows = decode_records(data["blob"])
                return [
                    {
                        "id": r.get("i", ""),
                        "qualified_name": r.get("q", ""),
                        "kind": r.get("k", ""),
                        "path": r.get("f", ""),
                        "start_line": r.get("s", ""),
                        "end_line": r.get("e", ""),
                        "docstring": r.get("d", ""),
                    }
                    for r in rows
                ]
            return data.get("symbols", [])
        except Exception as e:
            log.debug("code search failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Core reasoning
    # ------------------------------------------------------------------

    async def think(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        reasoning_depth: Optional[str] = None,
    ) -> MindResponse:
        """Process a question through the full reasoning pipeline.

        This is the single entry point for an agent that wants the
        mind's perspective.  Returns a `MindResponse` with the
        reasoned answer, confidence, proactive context, and the
        reasoning trace.

        Pipeline (PR #10):
        1. Retrieve memories
        2. Optional graph expansion (1-2 related memories the embedding missed)
        3. Clarification check
        4. Deterministic reasoning (always) + LLM multi-step pipeline (extract
           → reason → verify) when an LLM is wired
        5. Opinion formation (LLM if available, else deterministic)
        6. Proactive surfacing (LLM + deterministic merged)
        7. Compose + learn
        """
        depth = ReasoningDepth(reasoning_depth) if reasoning_depth else self.config.reasoning_depth
        context = context or {}

        # Step 1: Retrieve memories the rest of the pipeline will operate on
        memories = await self._retrieve_memories(question, context)

        # Step 1b: Optional graph expansion — pull 1-2 related memories the
        # embedding search missed.  Free (no LLM), pure DB.
        related_lookup: Dict[str, List[str]] = {}
        if self.config.enable_related_graph and memories:
            related_lookup = await self._expand_via_graph(memories)

        # Step 1c: Code-context integration.  If the question is about
        # "how does X work" or "show me the code for Y", query the code
        # index and inject symbol cards into the LLM prompt.  The cards
        # ride alongside the memories — the LLM uses whichever fits.
        code_symbols: List[Dict[str, Any]] = []
        if _looks_like_code_question(question):
            code_symbols = await self._code_search(question, limit=5)
            if code_symbols:
                log.info("code-context: %d symbols injected for %r",
                         len(code_symbols), question[:60])

        # Step 2: Decide whether we need to ask for clarification
        if self._needs_clarification(question, memories):
            clarifying_q = await self._form_clarifying_question(question, memories)
            return MindResponse(
                answer=None,
                clarifying_question=clarifying_q,
                confidence=0.0,
                memories_cited=[m.get("id") for m in memories if m.get("id")],
            )

        # Step 3: Deterministic reasoning + LLM enrichment.
        reasoning = await self.reasoning.reason(
            question=question,
            memories=memories,
            identity=self.identity,
            depth=depth,
        )

        llm_pipeline_result: Optional[Dict[str, Any]] = None
        # The LLM is the mind — it runs at every depth.  FAST skips the
        # heavy extract/verify pre-steps but still goes through the LLM
        # to generate the actual answer.  Without the LLM at FAST, the
        # response is just the top recall hit, which is not a mind.
        if self.llm is not None:
            try:
                from app.mind.llm_reasoning import (
                    is_llm_available,
                    run_pipeline,
                    enrich_reasoning_result,
                )
                if is_llm_available(self.llm):
                    llm_pipeline_result = await run_pipeline(
                        question=question,
                        memories=memories,
                        llm_client=self.llm,
                        llm_fallback=self.llm_fallback,
                        primary_model=self.config.llm_model,
                        fallback_model=self.config.fallback_llm_model,
                        depth=depth.value,
                        enable_extract=self.config.enable_extract,
                        enable_verify=self.config.enable_verify,
                        enable_proactive_llm=self.config.enable_llm_proactive,
                        enable_opinion_llm=self.config.enable_llm_opinion,
                        max_memories=self.config.max_memories,
                        related_lookup=related_lookup,
                        code_symbols=code_symbols,
                    )
                    llm_result = llm_pipeline_result.get("reason")
                    if llm_result is not None and not llm_result.error and llm_result.answer:
                        reasoning = enrich_reasoning_result(reasoning, llm_result)
                    # Self-repair: if the pipeline flagged a problem, the
                    # LLM patches memory/mind state and the response surfaces
                    # what it fixed.  This is the mind keeping itself healthy.
                    repairs = await self._self_repair(
                        question=question,
                        llm_pipeline_result=llm_pipeline_result,
                        memories=memories,
                        depth=depth,
                    )
                    if repairs:
                        reasoning.answer = self._merge_repair_answer(
                            reasoning.answer, repairs
                        )
            except Exception as e:
                log.debug("LLM pipeline failed, using deterministic: %s", e)

        # Step 4: Form or update opinions.  Prefer the LLM's opinion when
        # the pipeline ran.
        opinions: List[Opinion] = []
        if self.config.enable_opinions and reasoning.confidence >= 0.6:
            topic = self._extract_topic(question)
            if topic:
                llm_op = None
                if llm_pipeline_result is not None and self.config.enable_llm_opinion:
                    llm_op = llm_pipeline_result.get("opinion")
                    if llm_op is not None and getattr(llm_op, "error", None):
                        llm_op = None
                opinion = await self.opinions.form_or_update(
                    topic=topic,
                    evidence=memories,
                    current_stance_hint=reasoning.stance_hint,
                    llm_opinion=llm_op,
                )
                if opinion is not None:
                    opinions.append(opinion)

        # Step 5: Identify proactive context (LLM + deterministic merged)
        proactive: List[ProactiveItem] = []
        if self.config.enable_proactive:
            llm_pro = None
            if (
                llm_pipeline_result is not None
                and self.config.enable_llm_proactive
                and depth != ReasoningDepth.FAST
            ):
                llm_pro = llm_pipeline_result.get("proactive")
                if llm_pro is not None and getattr(llm_pro, "error", None):
                    llm_pro = None
            proactive = await self.proactive.identify_context(
                question=question,
                memories=memories,
                agent_id=context.get("agent_id"),
                llm_proactive=llm_pro,
            )

        # Step 6: Compose the final answer
        answer = self._compose_answer(reasoning, opinions, proactive, memories)

        # Step 7: Learn from this interaction (when enabled)
        if self.config.enable_learning:
            await self.learning.learn_from_interaction(
                agent_id=context.get("agent_id", "unknown"),
                question=question,
                response=MindResponse(
                    answer=answer,
                    reasoning_trace=reasoning,
                    confidence=reasoning.confidence,
                    proactive_context=proactive,
                    memories_cited=memories,
                    opinions_expressed=opinions,
                ),
            )

        log.info("mind.think returning: code_symbols=%d", len(code_symbols))
        return MindResponse(
            answer=answer,
            reasoning_trace=reasoning,
            confidence=reasoning.confidence,
            proactive_context=proactive,
            memories_cited=memories,
            opinions_expressed=opinions,
            code_symbols=code_symbols,
        )

    async def reflect(
        self,
        topic: str,
        depth: str = "mid",
    ) -> MindResponse:
        """Deep reflection on a topic — synthesises many memories into
        a single thoughtful narrative.  Distinct from `think()`:
        this is a monologue, not a Q&A.
        """
        # Pull a wider memory slice for reflection
        memories = await self._retrieve_memories(topic, {}, limit=self.config.max_memories * 2)
        reasoning = await self.reasoning.reflect(topic=topic, memories=memories, depth=depth)
        answer = self._compose_reflection(reasoning, memories)
        return MindResponse(
            answer=answer,
            reasoning_trace=reasoning,
            confidence=reasoning.confidence,
            memories_cited=memories,
        )

    # ------------------------------------------------------------------
    # Identity surface
    # ------------------------------------------------------------------

    def get_self_description(self) -> str:
        """Render a natural language description of who this mind is."""
        return self.identity.describe()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _retrieve_memories(
        self,
        question: str,
        context: Dict[str, Any],
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Pull relevant memories through the existing Nexus recall.

        Honours two scope filters that the Mind recognises:
          - `context["container_tag"]` — only memories in that tag
          - `context["scope"]`           — only memories in that scope
            (wing.room.drawer — matches as a prefix)

        If no memory store is wired (e.g. in pure unit tests), we
        return an empty list — the rest of the pipeline tolerates this.
        """
        if self.memory is None:
            return []
        limit = limit or self.config.max_memories
        container_tag = context.get("container_tag")
        scope = context.get("scope")
        try:
            memories = await self.memory.recall(
                query=question,
                agent_id=context.get("agent_id"),
                limit=limit,
                mind_id=self.mind_id,
                container_tag=container_tag,
                scope=scope,
            )
            # If container_tag or scope was set but the recall didn't
            # filter (the underlying store may not support it), do an
            # in-process filter as a fallback.
            if container_tag:
                memories = [m for m in memories if m.get("container_tag") == container_tag]
            if scope:
                from app.adopted import scope as _scope_mod
                # Normalize the scope filter (case + form)
                scope_norm = _scope_mod.normalize(scope)
                memories = [
                    m for m in memories
                    if m.get("scope") and _scope_mod.matches(scope_norm, m["scope"])
                ]
            return memories
        except Exception as e:
            log.warning("mind recall failed: %s", e)
            return []

    def _needs_clarification(self, question: str, memories: List[Dict[str, Any]]) -> bool:
        """Decide whether the question is too vague to answer.

        Heuristic: question is short, no memories match, and the
        question contains pronouns or deictic references that need
        more context.  Real callers can override the threshold.
        """
        if len(memories) >= self.config.min_clarification_threshold:
            return False
        if not question or len(question.strip()) < 5:
            return True
        vague = {"this", "that", "it", "those", "these", "stuff", "things", "something"}
        low = question.lower()
        if any(f" {w} " in f" {low} " for w in vague) and len(memories) < 2:
            return True
        return False

    async def _form_clarifying_question(self, question: str, memories: List[Dict[str, Any]]) -> str:
        """Ask back.  We don't need the LLM for this — the question is
        short and the template is the same every time."""
        if memories:
            return (
                f"Your question '{question}' matched a few memories but not strongly. "
                "Could you be more specific about which aspect you want to know about?"
            )
        return (
            f"I don't have any memories matching '{question}'. "
            "Could you rephrase or add more context?"
        )

    def _extract_topic(self, question: str) -> Optional[str]:
        """Heuristic topic extraction: take the longest noun-phrase-ish
        chunk of the question.  Good enough as a default; the LLM
        can refine during reasoning."""
        words = [w for w in question.split() if len(w) > 3]
        if not words:
            return None
        # Prefer the longest "topic-like" word
        return max(words, key=len).lower().strip("?.!")

    async def _expand_via_graph(
        self,
        memories: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        """Pull 1-2 related memories per top memory from the graph.

        Returns `{memory_id: [related_id, ...]}` so the formatter can
        surface them.  This is a no-LLM, DB-only pass that helps the
        LLM see connections the embedding search missed.
        """
        if not memories or not self.memory:
            return {}
        out: Dict[str, List[str]] = {}
        for m in memories[: min(len(memories), 8)]:
            mid = m.get("id")
            if not mid:
                continue
            try:
                related = await self.memory.get_related(memory_id=mid, limit=2)
            except Exception as e:
                log.debug("graph expand failed for %s: %s", mid, e)
                continue
            if related:
                out[mid] = [r.get("id") for r in related if r.get("id")]
        return out

    def _compose_answer(
        self,
        reasoning: ReasoningResult,
        opinions: List[Opinion],
        proactive: List[ProactiveItem],
        memories: List[Dict[str, Any]],
    ) -> str:
        """Stitch the reasoning output, opinions, and proactive context
        into a single natural language answer."""
        parts = [reasoning.conclusion or ""]
        if opinions:
            parts.append("\n\nMy take:")
            for op in opinions:
                stance = op.stance.value if hasattr(op.stance, "value") else str(op.stance)
                parts.append(f"- **{op.topic}**: {stance} (strength {op.strength:.2f}, {op.evidence_count} pieces of evidence)")
        if proactive:
            parts.append("\n\nProactive context:")
            for item in proactive[:3]:
                parts.append(f"- {item.content}")
        return "\n".join(p for p in parts if p).strip()
    def _compose_reflection(self, reasoning: ReasoningResult, memories: List[Dict[str, Any]]) -> str:
        """Render a reflection as a single coherent narrative paragraph."""
        return reasoning.conclusion or "No reflection available."

    # ── Self-repair ─────────────────────────────────────────────────────────
    # The LLM is not just an answer machine — it is the mind's immune
    # system.  When the recall returns nothing, when an LLM call errors,
    # when claims contradict, or when the agent's environment looks
    # broken, the mind saves a repair memory and reports what it fixed.
    # Repairs are durable: they survive restarts and are searchable.
    async def _self_repair(
        self,
        question: str,
        llm_pipeline_result: Optional[Dict[str, Any]],
        memories: List[Dict[str, Any]],
        depth: "ReasoningDepth",
    ) -> List[str]:
        """Inspect the LLM pipeline output and the recall set for failure
        modes, then save repair memories for any that are detected.

        Returns a list of human-readable repair notes (empty if the mind
        is healthy).  The notes are prepended to the final answer so the
        user sees what the mind did to keep itself running.
        """
        repairs: List[str] = []
        if not llm_pipeline_result:
            return repairs

        # 1. Empty recall: the agent asked something the mind has no
        #    memory of.  Save a marker so the mind knows it has a gap.
        if not memories:
            note = await self._save_repair_memory(
                kind="recall_gap",
                content=(
                    f"Recall gap: question '{question[:120]}' returned no "
                    f"memories.  The mind has no record of this topic yet."
                ),
                importance=0.4,
            )
            if note:
                repairs.append(note)

        # 2. LLM errored: the primary model failed.  Note the model
        #    failure so the next sync can detect a pattern.
        reason = llm_pipeline_result.get("reason")
        if reason is not None and getattr(reason, "error", None):
            err = str(reason.error)[:200]
            note = await self._save_repair_memory(
                kind="llm_error",
                content=(
                    f"LLM error on question '{question[:80]}': {err}. "
                    f"Pipeline fell back to deterministic reasoning."
                ),
                importance=0.5,
            )
            if note:
                repairs.append(note)

        # 3. Proactive/opinion steps errored: the LLM partially failed.
        for step_name in ("proactive", "opinion", "verification"):
            step = llm_pipeline_result.get(step_name)
            if step is not None and getattr(step, "error", None):
                err = str(step.error)[:160]
                note = await self._save_repair_memory(
                    kind=f"{step_name}_error",
                    content=f"{step_name} step errored: {err}",
                    importance=0.4,
                )
                if note:
                    repairs.append(note)

        # 4. No memories cited but the LLM gave an answer — possible
        #    hallucination.  Note it so the user can be skeptical.
        if (
            reason is not None
            and reason.answer
            and not reason.error
            and not memories
        ):
            note = await self._save_repair_memory(
                kind="unsupported_answer",
                content=(
                    f"Answer for '{question[:80]}' was generated without "
                    f"any cited memories — possible hallucination."
                ),
                importance=0.45,
            )
            if note:
                repairs.append(note)

        # 5. Stale retrieval: every cited memory is older than 30 days.
        #    The mind's recall found something but it is not fresh.
        from datetime import datetime, timezone
        cutoff = 30
        now = datetime.now(timezone.utc)
        if memories:
            all_old = True
            for m in memories:
                ts = m.get("created_at")
                if not ts:
                    continue
                try:
                    when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if (now - when).days < cutoff:
                        all_old = False
                        break
                except Exception:
                    all_old = False
                    break
            if all_old:
                note = await self._save_repair_memory(
                    kind="stale_recall",
                    content=(
                        f"All {len(memories)} memories cited for "
                        f"'{question[:60]}' are older than {cutoff} days. "
                        f"Mind should request fresh sync."
                    ),
                    importance=0.5,
                )
                if note:
                    repairs.append(note)

        return repairs

    async def _save_repair_memory(
        self,
        kind: str,
        content: str,
        importance: float = 0.5,
    ) -> Optional[str]:
        """Persist a self-repair memory.  Returns a short summary line
        that can be surfaced to the user, or None on failure."""
        if self.memory is None:
            return None
        try:
            result = await self.memory.save(
                content=content,
                agent_id=f"mind-repair-{self.mind_id}",
                memory_type="observation",
                importance=importance,
                tags=[
                    "self-repair",
                    f"repair:{kind}",
                    f"mind:{self.mind_id}",
                ],
            )
            mid = (result or {}).get("id")
            if mid:
                return f"self-repair: {kind} (memory {str(mid)[:8]})"
        except Exception as e:
            log.debug("self-repair save failed for kind=%s: %s", kind, e)
        return None

    def _merge_repair_answer(self, original: Optional[str], repairs: List[str]) -> str:
        """Prepend repair notes to the answer so the user sees what
        the mind fixed during this think() call."""
        if not repairs:
            return original or ""
        bullet_lines = "\n".join(f"  • {r}" for r in repairs)
        prefix = f"⚙ mind self-repair:\n{bullet_lines}\n"
        if original:
            return f"{prefix}\n{original}"
        return prefix.rstrip()



__all__ = [
    "LivingMind",
    "MindConfig",
    "MindResponse",
    "ReasoningDepth",
]
