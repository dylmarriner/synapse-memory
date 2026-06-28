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
        llm_client: Any = None,     # The LLM client used for reasoning
    ) -> None:
        self.mind_id = mind_id
        self.config = config or MindConfig()
        self.memory = memory_store
        self.llm = llm_client
        # Optional secondary LLM (e.g. DeepSeek) used when the primary
        # (local Ollama) call fails or returns nothing.  Wired by the router.
        self.llm_fallback = None

        # Subsystems — wired up here so the rest of the code can
        # reach them via the mind (mind.reasoning, mind.identity, ...)
        self.reasoning = ReasoningEngine(llm_client=llm_client)
        self.identity = Identity(mind_id=mind_id)
        self.opinions = OpinionSystem(mind_id=mind_id)
        self.proactive = ProactiveSurfacing(mind_id=mind_id, memory_store=memory_store)
        self.learning = LearningSystem(mind_id=mind_id, identity=self.identity, opinions=self.opinions, memory_store=memory_store)
        self.conversations = ConversationManager(mind_id=mind_id, mind=self)

        log.info("Living mind '%s' initialised (depth=%s)", mind_id, self.config.reasoning_depth.value)

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
        """
        depth = ReasoningDepth(reasoning_depth) if reasoning_depth else self.config.reasoning_depth
        context = context or {}

        # Step 1: Retrieve memories the rest of the pipeline will operate on
        memories = await self._retrieve_memories(question, context)

        # Step 2: Decide whether we need to ask for clarification
        if self._needs_clarification(question, memories):
            clarifying_q = await self._form_clarifying_question(question, memories)
            return MindResponse(
                answer=None,
                clarifying_question=clarifying_q,
                confidence=0.0,
                memories_cited=[m.get("id") for m in memories if m.get("id")],
            )

        # Step 3: Reason — the heavy lift.  Produces patterns, insights, conclusion.
        # First the deterministic pipeline runs (always available), then
        # if an LLM is wired, we enrich the result with one model call.
        reasoning = await self.reasoning.reason(
            question=question,
            memories=memories,
            identity=self.identity,
            depth=depth,
        )
        if self.llm is not None and depth != ReasoningDepth.FAST:
            # One LLM call replaces the conclusion with a higher-quality
            # reasoned answer.  Skipped in fast mode to keep latency low.
            # Try the primary (local Ollama) model first; if it errors or
            # returns nothing, fall back to the secondary (DeepSeek) model.
            try:
                from app.mind.llm_reasoning import (
                    is_llm_available,
                    llm_reason,
                    enrich_reasoning_result,
                )
                llm_result = None
                if is_llm_available(self.llm):
                    llm_result = await llm_reason(
                        question=question,
                        memories=memories,
                        llm_client=self.llm,
                        model=self.config.llm_model,
                    )
                # Fallback: primary unavailable, errored, or produced no answer.
                if (llm_result is None or llm_result.error or not llm_result.answer) \
                        and is_llm_available(self.llm_fallback):
                    log.debug("mind '%s' primary LLM unproductive — trying fallback %s",
                              self.mind_id, self.config.fallback_llm_model)
                    fb = await llm_reason(
                        question=question,
                        memories=memories,
                        llm_client=self.llm_fallback,
                        model=self.config.fallback_llm_model,
                    )
                    if fb and not fb.error and fb.answer:
                        llm_result = fb
                if llm_result is not None:
                    reasoning = enrich_reasoning_result(reasoning, llm_result)
            except Exception as e:
                log.debug("LLM enrichment failed, using deterministic: %s", e)

        # Step 4: Form or update opinions if the evidence warrants it
        opinions: List[Opinion] = []
        if self.config.enable_opinions and reasoning.confidence >= 0.6:
            topic = self._extract_topic(question)
            if topic:
                opinion = await self.opinions.form_or_update(
                    topic=topic,
                    evidence=memories,
                    current_stance_hint=reasoning.stance_hint,
                )
                if opinion is not None:
                    opinions.append(opinion)

        # Step 5: Identify proactive context (always-on if enabled)
        proactive: List[ProactiveItem] = []
        if self.config.enable_proactive:
            proactive = await self.proactive.identify_context(
                question=question,
                memories=memories,
                agent_id=context.get("agent_id"),
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

        return MindResponse(
            answer=answer,
            reasoning_trace=reasoning,
            confidence=reasoning.confidence,
            proactive_context=proactive,
            memories_cited=memories,
            opinions_expressed=opinions,
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


__all__ = [
    "LivingMind",
    "MindConfig",
    "MindResponse",
    "ReasoningDepth",
]
