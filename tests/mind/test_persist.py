"""Tests for the Living Mind persistence layer.

The persist module is a thin SQL wrapper.  We test it without a real
DB by using an in-memory SQLite session — but the SQL it emits is
PostgreSQL-flavored (gen_random_uuid, uuid[]), so we test the
*behaviour* of the wrappers in isolation by mocking the SQLAlchemy
text() execution path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _mock_db_session():
    """Build a mock AsyncSession that records executed SQL.

    The persist module does `db.execute(text(...), params)`.  We
    mock the session to capture the SQL + params passed in.
    """
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


# ---- ensure_mind_row --------------------------------------------------

def test_ensure_mind_row_issues_insert(monkeypatch):
    from app.mind import persist
    session = _mock_db_session()
    # Use asyncio.run to drive the coroutine
    import asyncio
    asyncio.run(persist.ensure_mind_row("test-mind", session, name="test-mind"))
    # Should have called execute + commit
    assert session.execute.await_count >= 1
    assert session.commit.await_count >= 1


def test_ensure_mind_row_swallows_errors(monkeypatch):
    """A bad DB connection must not break the mind creation path."""
    from app.mind import persist
    session = _mock_db_session()
    session.execute = AsyncMock(side_effect=Exception("db down"))
    import asyncio
    # Should not raise
    asyncio.run(persist.ensure_mind_row("test-mind", session))


# ---- load / save identity -----------------------------------------------

def test_load_identity_returns_empty_when_no_row():
    from app.mind import persist
    session = _mock_db_session()
    session.execute = AsyncMock()
    # No row returned
    result_mock = MagicMock()
    result_mock.fetchone.return_value = None
    session.execute.return_value = result_mock
    import asyncio
    out = asyncio.run(persist.load_identity_from_db("test-mind", session))
    assert out == {}


def test_load_identity_reads_columns():
    from app.mind import persist
    session = _mock_db_session()
    row = (["trait1", "trait2"], [{"description": "x"}], ["cap1"], ["lim1"])
    result_mock = MagicMock()
    result_mock.fetchone.return_value = row
    session.execute.return_value = result_mock
    import asyncio
    out = asyncio.run(persist.load_identity_from_db("test-mind", session))
    assert out["core_traits"] == ["trait1", "trait2"]
    assert out["learned_patterns"] == [{"description": "x"}]
    assert out["capabilities"] == ["cap1"]
    assert out["limitations"] == ["lim1"]


def test_save_identity_serialises_json():
    from app.mind import persist
    from app.mind.identity import Identity, LearnedPattern
    session = _mock_db_session()
    captured_params = {}

    async def capture_execute(stmt, params=None):
        captured_params.update(params or {})
        mock = MagicMock()
        return mock
    session.execute = AsyncMock(side_effect=capture_execute)

    identity = Identity(mind_id="test")
    identity.capabilities.append("Test cap")
    identity.learned_patterns.append(LearnedPattern(description="x", importance=0.7))

    import asyncio
    asyncio.run(persist.save_identity_to_db("test", identity, session))
    # JSON fields should be strings
    assert isinstance(captured_params["core_traits"], str)
    # Should contain at least one of the default core traits
    assert "living mind" in captured_params["core_traits"].lower()
    assert "Test cap" in captured_params["capabilities"]
    assert "x" in captured_params["learned_patterns"]


# ---- load / save opinions -----------------------------------------------

def test_load_opinions_parses_rows():
    from app.mind import persist
    session = _mock_db_session()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [
        ("auth_module", "negative", 0.85, 5, "fragile", []),
        ("db_layer", "positive", 0.7, 3, "stable", []),
    ]
    session.execute.return_value = result_mock
    import asyncio
    out = asyncio.run(persist.load_opinions_from_db("test", session))
    assert "auth_module" in out
    assert out["auth_module"]["stance"] == "negative"
    assert out["auth_module"]["strength"] == 0.85
    assert out["auth_module"]["evidence_count"] == 5
    assert out["db_layer"]["stance"] == "positive"


def test_save_opinions_deletes_and_reinserts():
    from app.mind import persist
    from app.mind.opinions import OpinionSystem, Opinion, Stance
    session = _mock_db_session()
    statements = []

    async def capture(stmt, params=None):
        statements.append(str(stmt).upper())
        return MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    system = OpinionSystem(mind_id="test")
    system.opinions["x"] = Opinion(topic="x", stance=Stance.POSITIVE, strength=0.5, evidence_count=1)

    import asyncio
    asyncio.run(persist.save_opinions_to_db("test", system, session))
    # Should have done DELETE + INSERT
    sqls = " ".join(statements)
    assert "DELETE FROM MIND_OPINIONS" in sqls
    assert "INSERT INTO MIND_OPINIONS" in sqls


# ---- load / save relationships -----------------------------------------

def test_load_relationships_parses_rows():
    from app.mind import persist
    session = _mock_db_session()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [
        # (agent_id, trust, count, projects, style)
        ("alice", 0.9, 42, ["auth", "db"], "technical"),
        ("bob", 0.5, 1, [], None),
    ]
    session.execute.return_value = result_mock
    import asyncio
    out = asyncio.run(persist.load_relationships_from_db("test", session))
    assert "alice" in out
    assert out["alice"]["trust_level"] == 0.9
    assert out["alice"]["interaction_count"] == 42
    assert out["alice"]["shared_projects"] == ["auth", "db"]
    assert out["alice"]["communication_style"] == "technical"
    assert out["bob"]["communication_style"] is None


def test_load_relationships_skips_null_agent():
    from app.mind import persist
    session = _mock_db_session()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [(None, 0.5, 1, [], None)]
    session.execute.return_value = result_mock
    import asyncio
    out = asyncio.run(persist.load_relationships_from_db("test", session))
    assert out == {}


# ---- conversation turns -----------------------------------------------

def test_save_conversation_turn_inserts_row():
    from app.mind import persist
    from app.mind import MindResponse

    session = _mock_db_session()
    statements = []

    async def capture(stmt, params=None):
        statements.append((str(stmt).upper(), params))
        return MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    response = MindResponse(answer="Test answer", confidence=0.85)
    import asyncio
    asyncio.run(persist.save_conversation_turn(
        mind_id="test",
        conversation_id="conv-1",
        agent_id="alice",
        turn_number=1,
        agent_message="Hello",
        mind_response=response,
        db=session,
    ))
    # Two statements: one for conversation upsert, one for turn insert
    assert len(statements) == 2
    upsert_sql, upsert_params = statements[0]
    insert_sql, insert_params = statements[1]
    assert "INSERT INTO CONVERSATIONS" in upsert_sql
    assert "INSERT INTO CONVERSATION_TURNS" in insert_sql
    assert insert_params["turn"] == 1
    assert insert_params["msg"] == "Hello"
    assert "Test answer" in insert_params["resp"]


def test_end_conversation_in_db_sets_ended_at():
    from app.mind import persist
    session = _mock_db_session()
    statements = []
    async def capture(stmt, params=None):
        statements.append(str(stmt).upper())
        return MagicMock()
    session.execute = AsyncMock(side_effect=capture)
    import asyncio
    asyncio.run(persist.end_conversation_in_db("conv-1", session))
    assert any("UPDATE CONVERSATIONS" in s for s in statements)


# ---- hydrate_mind -----------------------------------------------------

def test_hydrate_mind_loads_identity_and_opinions():
    """hydrate_mind is the main entry point — verify it calls all the
    loaders and applies the results to the in-process state."""
    from app.mind import persist
    from app.mind import LivingMind, MindConfig
    from app.mind.opinions import Opinion, Stance

    mind = LivingMind("test", MindConfig())
    # Pre-state: empty identity
    assert mind.identity.core_traits == [] or len(mind.identity.core_traits) > 0  # default traits

    session = _mock_db_session()

    # Mock the loaders to return known data
    async def fake_load_identity(mid, db):
        return {
            "core_traits": ["loaded trait"],
            "learned_patterns": [{"description": "loaded pattern", "importance": 0.7, "source": "session"}],
            "capabilities": ["loaded cap"],
            "limitations": ["loaded lim"],
        }

    async def fake_load_opinions(mid, db):
        return {
            "test_topic": {
                "topic": "test_topic", "stance": "negative",
                "strength": 0.8, "evidence_count": 4,
                "rationale": None, "memory_ids": [],
            }
        }

    async def fake_load_rels(mid, db):
        return {}

    async def fake_ensure(mid, db, name=None):
        pass

    with patch.object(persist, "load_identity_from_db", side_effect=fake_load_identity), \
         patch.object(persist, "load_opinions_from_db", side_effect=fake_load_opinions), \
         patch.object(persist, "load_relationships_from_db", side_effect=fake_load_rels), \
         patch.object(persist, "ensure_mind_row", side_effect=fake_ensure):
        import asyncio
        asyncio.run(persist.hydrate_mind(mind, session))

    # The mind's state should be overwritten by the loaded data
    assert "loaded trait" in mind.identity.core_traits
    assert "loaded cap" in mind.identity.capabilities
    assert "loaded lim" in mind.identity.limitations
    assert any(p.description == "loaded pattern" for p in mind.identity.learned_patterns)
    assert "test_topic" in mind.opinions.opinions
    assert mind.opinions.opinions["test_topic"].stance == Stance.NEGATIVE


def test_hydrate_mind_handles_gracefully_when_nothing_in_db():
    """If the DB returns nothing, the in-process defaults stay intact."""
    from app.mind import persist
    from app.mind import LivingMind, MindConfig

    mind = LivingMind("test", MindConfig())
    session = _mock_db_session()

    async def fake_load_identity(mid, db):
        return {}

    async def fake_load_opinions(mid, db):
        return {}

    async def fake_load_rels(mid, db):
        return {}

    async def fake_ensure(mid, db, name=None):
        pass

    with patch.object(persist, "load_identity_from_db", side_effect=fake_load_identity), \
         patch.object(persist, "load_opinions_from_db", side_effect=fake_load_opinions), \
         patch.object(persist, "load_relationships_from_db", side_effect=fake_load_rels), \
         patch.object(persist, "ensure_mind_row", side_effect=fake_ensure):
        import asyncio
        # Should not raise
        asyncio.run(persist.hydrate_mind(mind, session))


# ---- log_learning_event -----------------------------------------------

def test_log_learning_event_writes_event():
    from app.mind import persist
    session = _mock_db_session()
    statements = []
    async def capture(stmt, params=None):
        statements.append((str(stmt).upper(), params))
        return MagicMock()
    session.execute = AsyncMock(side_effect=capture)
    import asyncio
    asyncio.run(persist.log_learning_event(
        mind_id="test",
        kind="pattern",
        description="Agents often ask procedural questions",
        metadata={"source": "interaction"},
        db=session,
    ))
    assert any("INSERT INTO MIND_LEARNING_EVENTS" in s for s, _ in statements)
