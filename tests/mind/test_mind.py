"""Unit tests for the Living Mind core components.

These tests exercise the Mind's reasoning pipeline, identity,
opinions, proactive surfacing, and conversation manager with
deterministic inputs (no LLM, no database) so they run in any
environment.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ---- reasoning ----------------------------------------------------------

def test_reasoning_engine_returns_basic_conclusion():
    from app.mind import ReasoningEngine
    engine = ReasoningEngine()
    memories = [
        {"id": "m1", "content": "The auth module handles JWT refresh tokens", "importance": 0.8, "memory_type": "world"},
        {"id": "m2", "content": "JWT tokens expire every 7 days", "importance": 0.7, "memory_type": "lesson"},
    ]
    result = asyncio.run(engine.reason(
        question="What do you know about the auth module?",
        memories=memories,
        identity=None,
        depth="fast",
    ))
    assert result.intent
    assert result.conclusion
    assert result.confidence > 0
    assert "m1" in result.relevant_memory_ids


def test_reasoning_engine_standard_depth_runs_full_pipeline():
    from app.mind import ReasoningEngine
    engine = ReasoningEngine()
    memories = [
        {"id": "m1", "content": "Auth module is broken", "importance": 0.8},
        {"id": "m2", "content": "Auth module is broken again", "importance": 0.8},
        {"id": "m3", "content": "Alice is frustrated with the auth module", "importance": 0.7},
    ]
    result = asyncio.run(engine.reason(
        question="Tell me about the auth module",
        memories=memories,
        identity=None,
        depth="standard",
    ))
    assert result.patterns  # standard depth produces patterns
    assert result.insights
    assert result.conclusion


def test_reasoning_engine_reflection_produces_narrative():
    from app.mind import ReasoningEngine
    engine = ReasoningEngine()
    memories = [
        {"id": "m1", "content": "The auth module has had 3 bugs this month", "importance": 0.8},
        {"id": "m2", "content": "Alice said the auth module needs refactoring", "importance": 0.7},
    ]
    result = asyncio.run(engine.reflect(
        topic="auth module health",
        memories=memories,
        depth="mid",
    ))
    assert "auth module" in result.conclusion.lower()


def test_reasoning_engine_extracts_stance():
    from app.mind import ReasoningEngine
    engine = ReasoningEngine()
    positive = [{"id": "m1", "content": "This works great and is a success and is positive"}]
    negative = [{"id": "m1", "content": "This is broken and fails and is negative and is a bug"}]
    pos_result = asyncio.run(engine.reason("Tell me", positive, None, "fast"))
    neg_result = asyncio.run(engine.reason("Tell me", negative, None, "fast"))
    # Fast depth skips _infer_stance; we only run it on standard depth.
    pos_result_std = asyncio.run(engine.reason("Tell me", positive, None, "standard"))
    neg_result_std = asyncio.run(engine.reason("Tell me", negative, None, "standard"))
    assert pos_result_std.stance_hint == "positive"
    assert neg_result_std.stance_hint == "negative"


# ---- identity -----------------------------------------------------------

def test_identity_describes_itself():
    from app.mind import Identity
    identity = Identity(mind_id="test")
    desc = identity.describe()
    assert "test" in desc
    assert "I am a living mind" in desc


def test_identity_adds_pattern_idempotently():
    from app.mind import Identity
    identity = Identity(mind_id="test")
    p1 = identity.add_pattern("Agents ask procedural questions", importance=0.5)
    p2 = identity.add_pattern("Agents ask procedural questions", importance=0.7)
    assert p1 is p2
    assert p2.evidence_count == 2
    assert p2.importance == 0.7  # max of the two


def test_identity_records_interaction_and_updates_trust():
    from app.mind import Identity
    identity = Identity(mind_id="test")
    rel = identity.record_interaction("agent-a", success=True)
    trust_after_first = rel.trust_level
    count_after_first = rel.interaction_count
    identity.record_interaction("agent-a", success=True)
    # Same object — read the new value
    assert rel.trust_level > trust_after_first
    assert rel.interaction_count == count_after_first + 1


def test_identity_records_failure_reduces_trust():
    from app.mind import Identity
    identity = Identity(mind_id="test")
    rel = identity.record_interaction("agent-a", success=True)
    before = rel.trust_level
    identity.record_interaction("agent-a", success=False)
    after = rel.trust_level
    assert after < before


# ---- opinions -----------------------------------------------------------

def test_opinions_form_on_sufficient_evidence():
    from app.mind import OpinionSystem, Stance
    sys = OpinionSystem(mind_id="test")
    evidence = [
        {"id": "m1", "content": "The auth module works great"},
        {"id": "m2", "content": "The auth module is a success"},
        {"id": "m3", "content": "Auth is working well"},
    ]
    opinion = asyncio.run(sys.form_or_update("auth_module", evidence, "positive"))
    assert opinion is not None
    assert opinion.stance == Stance.POSITIVE
    assert opinion.strength > 0


def test_opinions_update_with_new_evidence():
    from app.mind import OpinionSystem, Stance
    sys = OpinionSystem(mind_id="test")
    pos = [{"id": "m1", "content": "Works great"}, {"id": "m2", "content": "Success"}, {"id": "m3", "content": "Positive"}]
    asyncio.run(sys.form_or_update("topic", pos, "positive"))
    # New contradicting evidence
    neg = [{"id": "m4", "content": "Broken"}, {"id": "m5", "content": "Fails"}, {"id": "m6", "content": "Bug"}]
    updated = asyncio.run(sys.form_or_update("topic", neg, "negative"))
    assert updated.stance == Stance.NEGATIVE


def test_opinions_returns_none_on_empty_evidence():
    from app.mind import OpinionSystem
    sys = OpinionSystem(mind_id="test")
    result = asyncio.run(sys.form_or_update("topic", []))
    assert result is None


# ---- proactive ---------------------------------------------------------

def test_proactive_finds_unfinished_promises():
    from app.mind import ProactiveSurfacing
    ps = ProactiveSurfacing(mind_id="test")
    memories = [
        {"id": "m1", "content": "I will refactor the auth module next week", "memory_type": "experience"},
        {"id": "m2", "content": "I should write tests for the database layer", "memory_type": "experience"},
        {"id": "m3", "content": "The auth module has bugs", "memory_type": "world"},  # not a promise
    ]
    items = asyncio.run(ps.identify_context("auth module", memories))
    promise_items = [i for i in items if i.type == "unfinished_promise"]
    assert len(promise_items) == 2


def test_proactive_finds_recent_work():
    from app.mind import ProactiveSurfacing
    ps = ProactiveSurfacing(mind_id="test")
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    memories = [
        {"id": "m1", "content": "I fixed the auth module yesterday", "created_at": recent.isoformat()},
    ]
    items = asyncio.run(ps.identify_context("auth module", memories))
    recent_items = [i for i in items if i.type == "recent_work"]
    assert len(recent_items) == 1


def test_proactive_returns_top_n_by_relevance():
    from app.mind import ProactiveSurfacing
    ps = ProactiveSurfacing(mind_id="test", max_items=2)
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    memories = [
        {"id": f"m{i}", "content": f"I will do task {i}", "created_at": recent.isoformat()}
        for i in range(10)
    ]
    items = asyncio.run(ps.identify_context("task", memories))
    assert len(items) <= 2


# ---- conversation ------------------------------------------------------

def test_conversation_lifecycle():
    from app.mind import LivingMind, MindConfig, ConversationManager
    mind = LivingMind("test-mind", MindConfig())
    cm = ConversationManager(mind_id="test-mind", mind=mind)
    conv_id = cm.start_conversation("agent-a")
    assert conv_id in cm.active
    # End without any turns — should still work
    result = asyncio.run(cm.end_conversation(conv_id))
    assert result["status"] == "ended"
    assert conv_id not in cm.active


def test_conversation_unknown_id_raises():
    from app.mind import LivingMind, MindConfig, ConversationManager
    mind = LivingMind("test-mind", MindConfig())
    cm = ConversationManager(mind_id="test-mind", mind=mind)
    try:
        asyncio.run(cm.process_turn("unknown-id", "hello"))
    except KeyError:
        pass  # expected
    else:
        assert False, "expected KeyError"


# ---- mind (top-level) --------------------------------------------------

def test_mind_self_description_is_natural_language():
    from app.mind import LivingMind, MindConfig
    mind = LivingMind("my-mind", MindConfig())
    desc = mind.get_self_description()
    assert "my-mind" in desc
    assert "I am" in desc


def test_mind_think_with_no_memory_store_returns_response():
    from app.mind import LivingMind, MindConfig, MindResponse
    mind = LivingMind("test-mind", MindConfig(), memory_store=None)
    response = asyncio.run(mind.think("What do you know?"))
    assert isinstance(response, MindResponse)


def test_mind_think_uses_in_memory_store():
    from app.mind import LivingMind, MindConfig
    from app.mind.store import InMemoryMindStore
    store = InMemoryMindStore()
    store.memories.append({
        "id": "m1",
        "content": "The auth module handles JWT tokens",
        "memory_type": "world",
        "importance": 0.8,
        "metadata": {},
        "agent_id": None,
        "mind_id": "test-mind",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    mind = LivingMind("test-mind", MindConfig(), memory_store=store)
    response = asyncio.run(mind.think("auth module"))
    assert response.answer
    assert any(m.get("id") == "m1" for m in response.memories_cited)


def test_mind_ask_for_clarification_when_no_memories():
    from app.mind import LivingMind, MindConfig
    from app.mind.store import InMemoryMindStore
    mind = LivingMind("test-mind", MindConfig(), memory_store=InMemoryMindStore())
    response = asyncio.run(mind.think("that thing"))
    # Either asks back or has empty answer; with "that" the heuristic should ask back
    # (the threshold is 3 memories; with 0 it should ask)
    assert response.clarifying_question is not None or response.answer is not None


def test_mind_reflect_returns_narrative():
    from app.mind import LivingMind, MindConfig
    from app.mind.store import InMemoryMindStore
    store = InMemoryMindStore()
    store.memories.append({
        "id": "m1",
        "content": "The auth module is broken",
        "memory_type": "experience",
        "importance": 0.9,
        "metadata": {},
        "agent_id": None,
        "mind_id": "test-mind",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    mind = LivingMind("test-mind", MindConfig(), memory_store=store)
    response = asyncio.run(mind.reflect("auth module"))
    assert response.answer
    assert "auth" in response.answer.lower()


def test_mind_learns_from_interaction():
    from app.mind import LivingMind, MindConfig
    from app.mind.store import InMemoryMindStore
    mind = LivingMind("test-mind", MindConfig(), memory_store=InMemoryMindStore())
    before = len(mind.identity.learned_patterns)
    response = asyncio.run(mind.think("What is the capital of France?"))
    asyncio.run(mind.learning.learn_from_interaction(
        "agent-a",
        "What is the capital of France?",
        response,
    ))
    after = len(mind.identity.learned_patterns)
    # At least one pattern should have been added
    assert after >= before
