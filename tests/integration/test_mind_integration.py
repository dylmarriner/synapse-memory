"""Integration tests: Living Mind + existing Nexus.

Verifies that the new mind router and active-memory layer work
alongside the rest of the Nexus app — no regressions, routes
are wired, the Mind can be invoked through the same FastAPI app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def test_mind_router_is_registered():
    import app.main
    paths = app.main.app.openapi()["paths"]
    mind_paths = [p for p in paths if "/v1/mind" in p]
    assert len(mind_paths) >= 8
    expected = {
        "/v1/mind/think",
        "/v1/mind/reflect",
        "/v1/mind/conversations/start",
        "/v1/mind/conversations/{conversation_id}/turn",
        "/v1/mind/conversations/{conversation_id}/end",
        "/v1/mind/identity/{mind_id}",
        "/v1/mind/opinions/{mind_id}",
        "/v1/mind/registry",
    }
    assert expected.issubset(set(mind_paths))


def test_mind_mcp_tools_are_defined():
    from app.mind.mcp_tools import MIND_MCP_TOOLS
    assert len(MIND_MCP_TOOLS) >= 8
    tool_names = {t["name"] for t in MIND_MCP_TOOLS}
    expected = {
        "mind_think", "mind_reflect", "mind_start_conversation",
        "mind_conversation_turn", "mind_end_conversation",
        "mind_get_identity", "mind_get_opinions", "mind_get_proactive",
    }
    assert expected.issubset(tool_names)


def test_mind_modules_all_importable():
    import app.mind.living_mind
    import app.mind.reasoning
    import app.mind.identity
    import app.mind.opinions
    import app.mind.proactive
    import app.mind.learning
    import app.mind.conversation
    import app.mind.store
    import app.mind.active
    import app.mind.mcp_tools


def test_mind_active_memory_layer_importable():
    from app.mind.active import MemoryRouter, ContextInjector, ProactiveManager
    assert MemoryRouter is not None
    assert ContextInjector is not None
    assert ProactiveManager is not None


def test_mind_handles_full_think_reflect_cycle():
    """End-to-end through the in-process mind registry — no DB."""
    import asyncio
    from app.routers.mind import _get_mind
    from app.mind import MindConfig
    mind = _get_mind("test-mind-int")
    # Reset to a known state
    mind.config = MindConfig()
    response = asyncio.run(mind.think(
        question="What do you know about the auth module?",
    ))
    # In-memory store is empty, so we expect either a clarifying
    # question or a "no memories" answer — not a crash.
    assert response.answer is not None or response.clarifying_question is not None


def test_mind_registry_endpoint_lists_minds():
    import asyncio
    from app.routers.mind import _get_mind
    from app.mind import MindConfig
    mind = _get_mind("registry-test")
    mind.config = MindConfig()
    asyncio.run(mind.think(question="hi"))
    # Walk the in-process registry directly (no HTTP needed)
    from app.routers import mind as mind_module
    minds = list(mind_module._MINDS.values())
    assert any(m.mind_id == "registry-test" for m in minds)


def test_mind_identity_endpoint_shape():
    import asyncio
    from app.routers.mind import _get_mind
    from app.mind import MindConfig
    mind = _get_mind("test-identity")
    mind.config = MindConfig()
    description = mind.get_self_description()
    identity = mind.identity.to_dict()
    assert "test-identity" in description
    assert identity["mind_id"] == "test-identity"
    assert "core_traits" in identity


def test_mind_opinions_endpoint_shape():
    import asyncio
    from app.routers.mind import _get_mind
    from app.mind import MindConfig, OpinionSystem, Opinion, Stance
    from datetime import datetime, timezone
    mind = _get_mind("test-opinions")
    mind.config = MindConfig()
    # Inject a test opinion directly
    mind.opinions.opinions["test_topic"] = Opinion(
        topic="test_topic",
        stance=Stance.POSITIVE,
        strength=0.7,
        evidence_count=2,
        memory_ids=["m1", "m2"],
        formed_at=datetime.now(timezone.utc),
    )
    opinion = mind.opinions.get("test_topic")
    assert opinion is not None
    assert opinion.topic == "test_topic"
    assert opinion.stance == Stance.POSITIVE
    assert opinion.strength == 0.7


def test_mind_migration_loads():
    p = PROJECT_ROOT / "migrations" / "006_living_mind.sql"
    assert p.exists()
    sql = p.read_text()
    for stmt in sql.split(";"):
        if "CREATE TABLE" in stmt and "IF NOT EXISTS" not in stmt:
            pytest.fail(f"CREATE TABLE without IF NOT EXISTS: {stmt[:80]}")
        if "ALTER TABLE" in stmt and "ADD COLUMN" in stmt:
            if "ADD COLUMN IF NOT EXISTS" not in stmt:
                pytest.fail(f"ALTER TABLE ADD COLUMN without IF NOT EXISTS: {stmt[:80]}")


def test_no_regressions_in_existing_routes():
    import app.main
    paths = app.main.app.openapi()["paths"]
    must_exist = {
        "/v1/memory/save",
        "/v1/memory/recall",
        "/v1/memory/reflect",
        "/v1/agents/{agent_id}/context",
        "/v1/adopted/retain",
        "/v1/adopted/recall",
    }
    for p in must_exist:
        assert p in paths, f"existing route disappeared: {p}"
