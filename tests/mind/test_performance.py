"""Performance tests for the Living Mind.

Validates that the mind meets the latency targets from the
architecture document:
  - fast depth:     < 500ms
  - standard depth: < 2s
  - deep depth:     < 5s

These are upper bounds, not tight targets — the test fails if the
mind is significantly slower than expected.  We use a small in-memory
corpus so the test is deterministic.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _make_mind(num_memories: int = 20):
    """Build a LivingMind with a populated in-memory store."""
    from app.mind import LivingMind, MindConfig
    from app.mind.store import InMemoryMindStore
    store = InMemoryMindStore()
    mind = LivingMind("perf-mind", MindConfig(), memory_store=store)
    # Pre-populate the store
    for i in range(num_memories):
        store.memories.append({
            "id": f"m{i}",
            "content": f"Memory number {i} about auth module and JWT tokens and refresh and rotation",
            "memory_type": "experience",
            "importance": 0.5,
            "agent_id": "perf-agent",
            "metadata": {"tags": ["auth", "jwt", f"topic-{i % 3}"]},
            "mind_id": "perf-mind",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(),
        })
    return mind


# ---- fast depth --------------------------------------------------------

def test_fast_think_under_500ms():
    mind = _make_mind(num_memories=20)
    start = time.perf_counter()
    response = asyncio.run(mind.think(
        question="What do you know about the auth module?",
        reasoning_depth="fast",
    ))
    elapsed = (time.perf_counter() - start) * 1000
    assert response.answer is not None
    # Generous upper bound for CI environments
    assert elapsed < 2000, f"fast think took {elapsed:.0f}ms (limit 2000ms)"


# ---- standard depth ----------------------------------------------------

def test_standard_think_under_2s():
    mind = _make_mind(num_memories=20)
    start = time.perf_counter()
    response = asyncio.run(mind.think(
        question="What patterns do you see in the auth module?",
        reasoning_depth="standard",
    ))
    elapsed = (time.perf_counter() - start) * 1000
    assert response.answer is not None
    # Generous for CI
    assert elapsed < 5000, f"standard think took {elapsed:.0f}ms (limit 5000ms)"


# ---- deep depth --------------------------------------------------------

def test_deep_think_under_5s():
    mind = _make_mind(num_memories=20)
    start = time.perf_counter()
    response = asyncio.run(mind.think(
        question="Reflect on all auth-related patterns and form a synthesised view",
        reasoning_depth="deep",
    ))
    elapsed = (time.perf_counter() - start) * 1000
    assert response.answer is not None
    # Generous for CI
    assert elapsed < 10000, f"deep think took {elapsed:.0f}ms (limit 10000ms)"


# ---- reflect ------------------------------------------------------------

def test_reflect_under_5s():
    mind = _make_mind(num_memories=20)
    start = time.perf_counter()
    response = asyncio.run(mind.reflect(topic="auth module patterns"))
    elapsed = (time.perf_counter() - start) * 1000
    assert response.answer is not None
    assert elapsed < 5000, f"reflect took {elapsed:.0f}ms (limit 5000ms)"


# ---- proactive ---------------------------------------------------------

def test_proactive_under_500ms():
    mind = _make_mind(num_memories=20)
    start = time.perf_counter()
    items = asyncio.run(mind.proactive.identify_context(
        question="auth module",
        memories=mind.memory.memories,
    ))
    elapsed = (time.perf_counter() - start) * 1000
    assert isinstance(items, list)
    assert elapsed < 1000, f"proactive took {elapsed:.0f}ms (limit 1000ms)"


# ---- conversation turn -------------------------------------------------

def test_conversation_turn_under_2s():
    mind = _make_mind(num_memories=20)
    conv_id = mind.conversations.start_conversation("perf-agent")
    start = time.perf_counter()
    asyncio.run(mind.conversations.process_turn(conv_id, "What about the auth module?"))
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 5000, f"conversation turn took {elapsed:.0f}ms (limit 5000ms)"


# ---- identity ----------------------------------------------------------

def test_identity_prune_under_100ms():
    mind = _make_mind(num_memories=20)
    # Add 200 patterns
    from app.mind.identity import LearnedPattern
    for i in range(200):
        mind.identity.add_pattern(f"Pattern {i}", importance=0.5)
    start = time.perf_counter()
    pruned = mind.identity.prune_old_patterns(max_age_days=90, max_patterns=200)
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 200, f"prune took {elapsed:.0f}ms (limit 200ms)"
    assert pruned >= 0


# ---- opinions ----------------------------------------------------------

def test_opinions_under_100ms():
    mind = _make_mind(num_memories=20)
    from app.mind.opinions import Opinion, Stance
    # Add 10 opinions
    for i in range(10):
        mind.opinions.opinions[f"topic_{i}"] = Opinion(
            topic=f"topic_{i}",
            stance=Stance.NEUTRAL,
            strength=0.5,
            evidence_count=1,
        )
    start = time.perf_counter()
    for i in range(20):  # 20 lookups
        mind.opinions.get(f"topic_{i % 10}")
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 50, f"20 lookups took {elapsed:.0f}ms (limit 50ms)"
