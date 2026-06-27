"""Real-database integration test for the Living Mind persistence.

Uses SQLite in-memory mode + SQLAlchemy + aiosqlite to drive the
persist module through a real database.  This catches problems
that mock-based tests miss (e.g. SQL syntax, schema mismatches,
transaction issues).

The persist module is PostgreSQL-flavored (gen_random_uuid,
ON CONFLICT, jsonb, uuid[]).  We use a SQLite-compatible test
schema that mirrors the production one.  In production, migration
006 creates the schema; here we define it inline.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# Skip if SQLAlchemy async + aiosqlite not available
pytest.importorskip("sqlalchemy.ext.asyncio")
pytest.importorskip("aiosqlite")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# Mirror of migration 006's schema, translated for SQLite.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS minds (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    core_traits     TEXT NOT NULL DEFAULT '[]',
    learned_patterns TEXT NOT NULL DEFAULT '[]',
    capabilities    TEXT NOT NULL DEFAULT '[]',
    limitations     TEXT NOT NULL DEFAULT '[]',
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mind_opinions (
    id              TEXT PRIMARY KEY,
    mind_id         TEXT NOT NULL,
    topic           TEXT NOT NULL,
    stance           TEXT NOT NULL DEFAULT 'neutral',
    strength        REAL NOT NULL DEFAULT 0.5,
    evidence_count  INTEGER NOT NULL DEFAULT 0,
    rationale       TEXT,
    memory_ids      TEXT NOT NULL DEFAULT '[]',
    formed_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (mind_id, topic)
);

CREATE TABLE IF NOT EXISTS mind_relationships (
    id                  TEXT PRIMARY KEY,
    mind_id             TEXT NOT NULL,
    agent_id            TEXT,
    trust_level         REAL NOT NULL DEFAULT 0.5,
    interaction_count   INTEGER NOT NULL DEFAULT 0,
    shared_projects     TEXT NOT NULL DEFAULT '[]',
    communication_style TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    mind_id     TEXT NOT NULL,
    agent_id    TEXT,
    started_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at    TEXT,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    summary     TEXT,
    insights    TEXT NOT NULL DEFAULT '[]',
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    turn_number      INTEGER NOT NULL,
    agent_message    TEXT NOT NULL,
    mind_response    TEXT NOT NULL,
    reasoning_trace  TEXT,
    confidence      REAL,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (conversation_id, turn_number)
);

CREATE TABLE IF NOT EXISTS mind_learning_events (
    id          TEXT PRIMARY KEY,
    mind_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    description TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _split_statements(sql: str) -> list:
    """Split a multi-statement SQL string on ';' boundaries, dropping blanks."""
    out = []
    for raw in sql.split(";"):
        s = raw.strip()
        if s:
            out.append(s)
    return out


async def _make_db_session():
    """Build a fresh in-memory SQLite session with the mind schema applied."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # aiosqlite doesn't handle multi-statement SQL, so we
        # execute each CREATE TABLE separately.
        for stmt in _split_statements(SCHEMA_SQL):
            await conn.exec_driver_sql(stmt)
    session = AsyncSession(engine)
    return session, engine


async def _make_mind_row(session, mind_id="default", name="default"):
    from sqlalchemy import text
    await session.execute(text("""
        INSERT INTO minds (id, name, description) VALUES (:id, :name, :desc)
    """), {"id": mind_id, "name": name, "desc": "Test mind"})
    await session.commit()


# ---- identity ----------------------------------------------------------

def test_identity_roundtrip():
    from app.mind import persist
    from app.mind.identity import Identity, LearnedPattern

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)

            mind_id = "default"
            identity = Identity(mind_id=mind_id)
            identity.core_traits = ["test trait 1", "test trait 2"]
            identity.capabilities.append("custom capability")
            identity.limitations.append("custom limitation")
            identity.learned_patterns.append(LearnedPattern(description="pattern 1", importance=0.7))
            identity.learned_patterns.append(LearnedPattern(description="pattern 2", importance=0.4))

            await persist.save_identity_to_db(mind_id, identity, session)
            loaded = await persist.load_identity_from_db(mind_id, session)

            assert "test trait 1" in loaded["core_traits"]
            assert "test trait 2" in loaded["core_traits"]
            assert "custom capability" in loaded["capabilities"]
            assert "custom limitation" in loaded["limitations"]
            assert len(loaded["learned_patterns"]) == 2
            descriptions = {p["description"] for p in loaded["learned_patterns"]}
            assert descriptions == {"pattern 1", "pattern 2"}
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- opinions ----------------------------------------------------------

def test_opinions_roundtrip():
    from app.mind import persist
    from app.mind.opinions import OpinionSystem, Opinion, Stance

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            system = OpinionSystem(mind_id="default")
            system.opinions["auth"] = Opinion(
                topic="auth", stance=Stance.NEGATIVE, strength=0.85,
                evidence_count=5, rationale="fragile module",
            )
            system.opinions["db"] = Opinion(
                topic="db", stance=Stance.POSITIVE, strength=0.7,
                evidence_count=3, rationale="stable",
            )

            await persist.save_opinions_to_db("default", system, session)
            loaded = await persist.load_opinions_from_db("default", session)

            assert "auth" in loaded
            assert loaded["auth"]["stance"] == "negative"
            assert loaded["auth"]["strength"] == 0.85
            assert loaded["auth"]["evidence_count"] == 5
            assert "db" in loaded
            assert loaded["db"]["stance"] == "positive"
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- relationships ---------------------------------------------------

def test_relationships_roundtrip():
    from app.mind import persist
    from app.mind.identity import Identity, Relationship

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            identity = Identity(mind_id="default")
            identity.relationships["alice"] = Relationship(
                agent_id="alice", trust_level=0.9, interaction_count=42,
                shared_projects=["auth", "db"], communication_style="technical",
            )
            identity.relationships["bob"] = Relationship(
                agent_id="bob", trust_level=0.5, interaction_count=1,
            )

            await persist.save_relationships_to_db("default", identity, session)
            loaded = await persist.load_relationships_from_db("default", session)

            assert "alice" in loaded
            assert loaded["alice"]["trust_level"] == 0.9
            assert loaded["alice"]["interaction_count"] == 42
            assert loaded["alice"]["shared_projects"] == ["auth", "db"]
            assert loaded["alice"]["communication_style"] == "technical"
            assert "bob" in loaded
            assert loaded["bob"]["communication_style"] is None
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- conversation turn ------------------------------------------------

def test_conversation_turn_persists():
    from app.mind import persist
    from app.mind import MindResponse

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            conv_id = "conv-1"
            response = MindResponse(answer="Hello back", confidence=0.9)
            await persist.save_conversation_turn(
                mind_id="default",
                conversation_id=conv_id,
                agent_id="alice",
                turn_number=1,
                agent_message="Hello",
                mind_response=response,
                db=session,
            )
            history = await persist.load_conversation_history("default", conv_id, session)
            assert len(history) == 1
            assert history[0]["agent_message"] == "Hello"
            assert history[0]["response"]["answer"] == "Hello back"
            assert history[0]["confidence"] == 0.9
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


def test_conversation_multiple_turns():
    from app.mind import persist
    from app.mind import MindResponse

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            conv_id = "conv-multi"
            for i in range(1, 4):
                response = MindResponse(answer=f"Answer {i}", confidence=0.8)
                await persist.save_conversation_turn(
                    mind_id="default",
                    conversation_id=conv_id,
                    agent_id="alice",
                    turn_number=i,
                    agent_message=f"Message {i}",
                    mind_response=response,
                    db=session,
                )
            history = await persist.load_conversation_history("default", conv_id, session)
            assert len(history) == 3
            assert [h["turn_number"] for h in history] == [1, 2, 3]
            assert [h["agent_message"] for h in history] == ["Message 1", "Message 2", "Message 3"]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


def test_end_conversation_marks_ended_at():
    from app.mind import persist
    from app.mind import MindResponse
    from sqlalchemy import text

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            conv_id = "conv-end"
            response = MindResponse(answer="Hi", confidence=0.5)
            await persist.save_conversation_turn(
                mind_id="default", conversation_id=conv_id,
                agent_id=None, turn_number=1,
                agent_message="Hi", mind_response=response, db=session,
            )
            await persist.end_conversation_in_db(conv_id, session)
            result = await session.execute(text("""
                SELECT ended_at FROM conversations WHERE id = :id
            """), {"id": conv_id})
            row = result.fetchone()
            assert row[0] is not None
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- hydrate ---------------------------------------------------------

def test_hydrate_mind_loads_persisted_state():
    from app.mind import persist
    from app.mind import LivingMind, MindConfig
    from app.mind.opinions import Opinion, Stance
    from app.mind.identity import Identity, LearnedPattern

    async def go():
        session, engine = await _make_db_session()
        try:
            # Pre-populate the database
            await _make_mind_row(session, "restore-mind", "restore-mind")
            identity = Identity(mind_id="restore-mind")
            identity.core_traits = ["loaded trait"]
            identity.capabilities.append("loaded cap")
            identity.limitations.append("loaded lim")
            identity.learned_patterns.append(LearnedPattern(description="loaded pattern"))
            await persist.save_identity_to_db("restore-mind", identity, session)

            class FakeOS:
                def __init__(self):
                    self.opinions = {
                        "topic": Opinion(topic="topic", stance=Stance.NEUTRAL, strength=0.6, evidence_count=2)
                    }
            await persist.save_opinions_to_db("restore-mind", FakeOS(), session)

            # Now create a fresh mind and hydrate it
            mind = LivingMind("restore-mind", MindConfig())
            assert "loaded trait" not in mind.identity.core_traits  # default state

            await persist.hydrate_mind(mind, session)

            assert "loaded trait" in mind.identity.core_traits
            assert "loaded cap" in mind.identity.capabilities
            assert "loaded lim" in mind.identity.limitations
            assert any(p.description == "loaded pattern" for p in mind.identity.learned_patterns)
            assert "topic" in mind.opinions.opinions
            assert mind.opinions.opinions["topic"].strength == 0.6
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- learning events -------------------------------------------------

def test_log_learning_event_persists():
    from app.mind import persist
    from sqlalchemy import text

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            await persist.log_learning_event(
                mind_id="default",
                kind="pattern",
                description="Agents often ask procedural questions",
                metadata={"source": "interaction"},
                db=session,
            )
            result = await session.execute(text("""
                SELECT kind, description, source FROM mind_learning_events
                WHERE mind_id = 'default'
            """))
            row = result.fetchone()
            assert row[0] == "pattern"
            assert row[1] == "Agents often ask procedural questions"
            assert row[2] == "interaction"
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- opinion stance roundtrip via enum -------------------------------

def test_opinion_stance_enum_roundtrip():
    """Each stance enum value must survive the roundtrip."""
    from app.mind import persist
    from app.mind.opinions import OpinionSystem, Opinion, Stance

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session)
            system = OpinionSystem(mind_id="default")
            for stance in (Stance.POSITIVE, Stance.NEGATIVE, Stance.NEUTRAL):
                topic = f"topic_{stance.value}"
                system.opinions[topic] = Opinion(topic=topic, stance=stance, strength=0.5, evidence_count=1)

            await persist.save_opinions_to_db("default", system, session)
            loaded = await persist.load_opinions_from_db("default", session)

            for stance in (Stance.POSITIVE, Stance.NEGATIVE, Stance.NEUTRAL):
                topic = f"topic_{stance.value}"
                assert topic in loaded
                assert loaded[topic]["stance"] == stance.value
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())


# ---- full mind roundtrip ----------------------------------------------

def test_full_mind_save_and_rehydrate():
    """End-to-end: build a mind, save it, build a new one, rehydrate.

    This is the production scenario — the mind runs in process 1,
    saves to DB, process 1 dies, process 2 hydrates and continues.
    """
    from app.mind import persist
    from app.mind import LivingMind, MindConfig
    from app.mind.opinions import Opinion, Stance
    from app.mind.identity import LearnedPattern

    async def go():
        session, engine = await _make_db_session()
        try:
            await _make_mind_row(session, "roundtrip-mind", "roundtrip-mind")

            # ---- Process 1: build a mind, populate, save ----
            mind1 = LivingMind("roundtrip-mind", MindConfig())
            mind1.identity.add_pattern("Agents ask procedural questions", importance=0.7)
            mind1.identity.add_capability("Reasoning about auth")
            mind1.identity.add_limitation("Cannot read minds in other workspaces")
            mind1.opinions.opinions["auth"] = Opinion(
                topic="auth", stance=Stance.NEGATIVE, strength=0.8, evidence_count=4,
            )
            mind1.opinions.opinions["db"] = Opinion(
                topic="db", stance=Stance.POSITIVE, strength=0.6, evidence_count=2,
            )

            await persist.save_mind(mind1, session)

            # ---- Process 2: build a fresh mind, hydrate ----
            mind2 = LivingMind("roundtrip-mind", MindConfig())
            # Default state — none of the patterns/opinions
            assert len(mind2.identity.learned_patterns) == 0
            assert len(mind2.opinions.opinions) == 0

            # Hydrate
            await persist.hydrate_mind(mind2, session)

            # The hydrated mind should match the saved state
            descriptions = {p.description for p in mind2.identity.learned_patterns}
            assert "Agents ask procedural questions" in descriptions
            assert "Reasoning about auth" in mind2.identity.capabilities
            assert "Cannot read minds in other workspaces" in mind2.identity.limitations
            assert "auth" in mind2.opinions.opinions
            assert mind2.opinions.opinions["auth"].stance == Stance.NEGATIVE
            assert "db" in mind2.opinions.opinions
            assert mind2.opinions.opinions["db"].stance == Stance.POSITIVE
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(go())
