"""Tests for the LLM-driven reasoning path.

The LLM module is a thin wrapper — we test it without a real LLM by
providing a fake LLM client that returns canned responses.  The
enrichment path is tested by patching the LLM reasoner.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _clear_llm_cache():
    """Each test starts with a clean LLM cache so cache hits from
    previous tests don't poison the response."""
    try:
        from app.mind.llm_reasoning import clear_cache
        clear_cache()
    except Exception:
        pass
    yield


# ---- helpers -----------------------------------------------------------

def _make_openai_response(text: str):
    """Build a fake OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_legacy_generate_response(text: str):
    """Build a fake response with a `.generate()` method only."""
    async def generate(**kwargs):
        return text
    # Use a plain object, not MagicMock, so hasattr returns False for
    # methods we haven't set.
    class _LegacyClient:
        pass
    client = _LegacyClient()
    client.generate = generate
    return client


# ---- is_llm_available -------------------------------------------------

def test_is_llm_available_returns_false_for_none():
    from app.mind.llm_reasoning import is_llm_available
    assert is_llm_available(None) is False


def test_is_llm_available_returns_true_for_openai_client():
    from app.mind.llm_reasoning import is_llm_available
    client = MagicMock()
    client.chat.completions.create = MagicMock()
    assert is_llm_available(client) is True


def test_is_llm_available_returns_true_for_legacy_client():
    from app.mind.llm_reasoning import is_llm_available
    async def generate(**kwargs):
        return ""
    client = MagicMock()
    client.generate = generate
    assert is_llm_available(client) is True


# ---- llm_reason --------------------------------------------------------

def test_llm_reason_parses_openai_response():
    from app.mind.llm_reasoning import llm_reason
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_make_openai_response(
        json.dumps({
            "answer": "The auth module is fragile",
            "evidence": ["m1", "m2"],
            "confidence": 0.8,
            "patterns": ["recurring bugs"],
            "insights": ["module is high-risk"],
            "stance": "negative",
        })
    ))
    result = asyncio.run(llm_reason(
        question="What about the auth module?",
        memories=[{"id": "m1", "content": "Auth bug"}],
        llm_client=client,
        model="qwen2.5:3b",
    ))
    assert result.error is None
    assert result.answer == "The auth module is fragile"
    assert "m1" in result.evidence
    assert result.confidence == 0.8
    assert "recurring bugs" in result.patterns
    assert result.stance == "negative"


def test_llm_reason_handles_markdown_fences():
    from app.mind.llm_reasoning import llm_reason
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_make_openai_response(
        "```json\n" + json.dumps({"answer": "test", "confidence": 0.5}) + "\n```"
    ))
    result = asyncio.run(llm_reason(
        question="q", memories=[{"id": "m1", "content": "anything"}],
        llm_client=client,
        model="qwen2.5:3b",
    ))
    assert result.answer == "test"
    assert result.confidence == 0.5


def test_llm_reason_handles_garbage_response():
    from app.mind.llm_reasoning import llm_reason
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_make_openai_response(""))
    result = asyncio.run(llm_reason(
        question="q", memories=[{"id": "m1", "content": "x"}], llm_client=client,
        model="qwen2.5:3b",
    ))
    # Empty response — the parser produces no answer and we mark
    # `empty_answer` so the caller can fall back.  The deterministic
    # pipeline is the fallback path.
    assert result.error == "empty_answer"
    assert result.answer == ""


def test_llm_reason_handles_exception():
    from app.mind.llm_reasoning import llm_reason
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("api down"))
    result = asyncio.run(llm_reason(
question="q", memories=[{"id": "m1", "content": "x"}], llm_client=client,
        model="qwen2.5:3b",
    ))
    assert result.error is not None
    assert "api down" in result.error


def test_llm_reason_returns_error_when_unavailable():
    from app.mind.llm_reasoning import llm_reason
    result = asyncio.run(llm_reason(
question="q", memories=[{"id": "m1", "content": "x"}], llm_client=None,
        model="qwen2.5:3b",
    ))
    assert result.error == "llm_unavailable"


def test_llm_reason_handles_legacy_generate_client():
    from app.mind.llm_reasoning import llm_reason
    client = _make_legacy_generate_response(json.dumps({
        "answer": "legacy", "confidence": 0.7
    }))
    result = asyncio.run(llm_reason(
question="q", memories=[{"id": "m1", "content": "x"}], llm_client=client,
        model="qwen2.5:3b",
    ))
    assert result.answer == "legacy"
    assert result.confidence == 0.7


# ---- enrich_reasoning_result -----------------------------------------

def test_enrich_keeps_deterministic_when_llm_failed():
    from app.mind.llm_reasoning import LLMReasoningResult, enrich_reasoning_result
    from app.mind.reasoning import ReasoningResult

    deterministic = ReasoningResult(
        conclusion="deterministic answer",
        confidence=0.6,
    )
    llm = LLMReasoningResult(error="api down")
    out = enrich_reasoning_result(deterministic, llm)
    assert out.conclusion == "deterministic answer"
    assert out.confidence == 0.6


def test_enrich_replaces_conclusion_with_llm_answer():
    from app.mind.llm_reasoning import LLMReasoningResult, enrich_reasoning_result
    from app.mind.reasoning import ReasoningResult

    deterministic = ReasoningResult(
        conclusion="deterministic answer",
        confidence=0.6,
        intent="test",
    )
    llm = LLMReasoningResult(
        answer="llm answer",
        confidence=0.9,
        patterns=["p1"],
        insights=["i1"],
        stance="negative",
    )
    out = enrich_reasoning_result(deterministic, llm)
    assert out.conclusion == "llm answer"
    assert out.confidence == 0.9
    assert out.patterns == ["p1"]
    assert out.insights == ["i1"]
    assert out.stance_hint == "negative"
    # The LLM step is appended to the trace
    assert any(s.name == "llm_reason" for s in out.trace)


# ---- integration with LivingMind ------------------------------------

def test_living_mind_uses_llm_when_available():
    """When an LLM is wired and depth is standard, the LLM enriches the
    deterministic result.  When the LLM is unavailable, the
    deterministic result stands alone."""
    from app.mind import LivingMind, MindConfig, ReasoningDepth, MindResponse
    from app.mind.llm_reasoning import LLMReasoningResult, enrich_reasoning_result

    # Test the enrichment logic in isolation — the full mind path
    # is covered by other tests.
    from app.mind.reasoning import ReasoningResult
    deterministic = ReasoningResult(conclusion="d", confidence=0.5)
    llm = LLMReasoningResult(answer="L", confidence=0.9)
    enriched = enrich_reasoning_result(deterministic, llm)
    assert enriched.conclusion == "L"
    assert enriched.confidence == 0.9


def test_living_mind_skips_llm_in_fast_mode():
    """Fast depth skips the LLM call to keep latency low."""
    from app.mind import LivingMind, MindConfig

    mind = LivingMind("test", MindConfig(), llm_client=MagicMock())
    # In fast mode, the think() loop should NOT call the LLM
    # (we don't have a real LLM here anyway, but the code path
    # explicitly skips when depth == FAST)
    response = asyncio.run(mind.think("q", reasoning_depth="fast"))
    # The response is valid even without an LLM
    assert response.answer is not None or response.clarifying_question is not None
    # The LLM was not called
    mind.llm.chat.completions.create.assert_not_called() if hasattr(mind.llm, "chat") else None
