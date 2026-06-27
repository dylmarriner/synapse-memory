"""Persistence layer for the Living Mind.

The LivingMind class is pure-Python and works in-process.  This
module is the seam that lets the mind *persist* its state to the
Nexus database (the `minds`, `mind_opinions`, `conversations`,
`conversation_turns`, `mind_relationships`, and `mind_learning_events`
tables from migration 006).

Three operations:

  load_mind_from_db(mind_id, db)        - hydrate a mind from rows
  save_mind_to_db(mind, db)              - flush a mind's state
  save_conversation_turn(mind, conv, db) - append a turn to the log

In production, `load_mind_from_db` is called when a mind is first
referenced (lazy hydration) and `save_mind_to_db` is called on
session end and periodically (every N interactions).  In tests
and embedded use, both are no-ops.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.mind import LivingMind, Opinion, Identity

log = logging.getLogger("nexus.mind.persist")


async def ensure_mind_row(mind_id: str, db: Any, name: Optional[str] = None) -> None:
    """Make sure a `minds` row exists for `mind_id`.  Idempotent."""
    try:
        await db.execute(
            __import__("sqlalchemy").text("""
                INSERT INTO minds (id, name, description)
                VALUES (gen_random_uuid(), :name, '')
                ON CONFLICT (name) DO NOTHING
            """),
            {"name": name or mind_id},
        )
        await db.commit()
    except Exception as e:
        log.debug("ensure_mind_row failed: %s", e)


async def load_identity_from_db(mind_id: str, db: Any) -> Dict[str, Any]:
    """Read the identity row for a mind.  Returns {} if not found."""
    try:
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT core_traits, learned_patterns, capabilities, limitations
            FROM minds
            WHERE name = :name
        """), {"name": mind_id})
        row = result.fetchone()
        if not row:
            return {}
        # Columns are stored as JSON strings; decode on the way out.
        def _decode(val):
            if val is None:
                return []
            if isinstance(val, (list, dict)):
                return val
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except (ValueError, TypeError):
                    return []
            return []
        return {
            "core_traits": _decode(row[0]),
            "learned_patterns": _decode(row[1]),
            "capabilities": _decode(row[2]),
            "limitations": _decode(row[3]),
        }
    except Exception as e:
        log.debug("load_identity_from_db failed: %s", e)
        return {}


async def save_identity_to_db(mind_id: str, identity: Any, db: Any) -> None:
    """Flush an Identity object to the minds row."""
    try:
        from sqlalchemy import text
        # The cast `AS jsonb` is a Postgres idiom.  SQLite ignores the
        # cast and passes the bound parameter through unchanged, but
        # SQLAlchemy sometimes drops the parameter when the cast is
        # present on SQLite.  We use plain text columns everywhere and
        # do the JSON encoding/decoding in Python.
        await db.execute(text("""
            UPDATE minds
            SET core_traits      = :core_traits,
                learned_patterns = :learned_patterns,
                capabilities     = :capabilities,
                limitations      = :limitations,
                updated_at       = :updated_at
            WHERE name = :name
        """), {
            "name": mind_id,
            "core_traits": json.dumps(list(identity.core_traits)),
            "learned_patterns": json.dumps([
                p.to_dict() if hasattr(p, "to_dict") else p
                for p in identity.learned_patterns
            ]),
            "capabilities": json.dumps(list(identity.capabilities)),
            "limitations": json.dumps(list(identity.limitations)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.commit()
    except Exception as e:
        log.debug("save_identity_to_db failed: %s", e)


async def load_opinions_from_db(mind_id: str, db: Any) -> Dict[str, Dict[str, Any]]:
    """Read all opinions for a mind."""
    try:
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT topic, stance, strength, evidence_count, rationale, memory_ids
            FROM mind_opinions
            WHERE mind_id = (SELECT id FROM minds WHERE name = :name)
        """), {"name": mind_id})
        out: Dict[str, Dict[str, Any]] = {}
        for row in result.fetchall():
            topic, stance, strength, ev_count, rationale, mem_ids = row
            out[topic] = {
                "topic": topic,
                "stance": stance,
                "strength": float(strength or 0),
                "evidence_count": int(ev_count or 0),
                "rationale": rationale,
                "memory_ids": list(mem_ids or []),
            }
        return out
    except Exception as e:
        log.debug("load_opinions_from_db failed: %s", e)
        return {}


async def save_opinions_to_db(mind_id: str, opinions: Any, db: Any) -> None:
    """Flush all opinions for a mind."""
    try:
        from sqlalchemy import text
        # Delete existing and re-insert — opinions are a small set,
        # and the in-memory store is the source of truth.
        await db.execute(text("""
            DELETE FROM mind_opinions
            WHERE mind_id = (SELECT id FROM minds WHERE name = :name)
        """), {"name": mind_id})
        if opinions.opinions:
            for topic, op in opinions.opinions.items():
                await db.execute(text("""
                    INSERT INTO mind_opinions
                        (mind_id, topic, stance, strength, evidence_count,
                         rationale, memory_ids, formed_at, last_updated)
                    VALUES
                        ((SELECT id FROM minds WHERE name = :name),
                         :topic, :stance, :strength, :ev_count,
                         :rationale, :mem_ids, :formed_at, :last_updated)
                """), {
                    "name": mind_id,
                    "topic": op.topic,
                    "stance": op.stance.value if hasattr(op.stance, "value") else str(op.stance),
                    "strength": float(op.strength),
                    "ev_count": int(op.evidence_count),
                    "rationale": op.rationale,
                    "mem_ids": json.dumps(list(op.memory_ids or [])),
                    "formed_at": datetime.now(timezone.utc).isoformat(),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                })
        await db.commit()
    except Exception as e:
        log.debug("save_opinions_to_db failed: %s", e)


async def load_relationships_from_db(mind_id: str, db: Any) -> Dict[str, Dict[str, Any]]:
    """Read all relationships for a mind."""
    try:
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT agent_id, trust_level, interaction_count,
                   shared_projects, communication_style
            FROM mind_relationships
            WHERE mind_id = (SELECT id FROM minds WHERE name = :name)
        """), {"name": mind_id})
        out: Dict[str, Dict[str, Any]] = {}
        for row in result.fetchall():
            agent_id, trust, count, projects, style = row
            if agent_id is None:
                continue
            # shared_projects is stored as a JSON string
            if isinstance(projects, str):
                try:
                    projects = json.loads(projects)
                except (ValueError, TypeError):
                    projects = []
            elif projects is None:
                projects = []
            out[str(agent_id)] = {
                "agent_id": str(agent_id),
                "trust_level": float(trust or 0.5),
                "interaction_count": int(count or 0),
                "shared_projects": list(projects or []),
                "communication_style": style,
            }
        return out
    except Exception as e:
        log.debug("load_relationships_from_db failed: %s", e)
        return {}


async def save_relationships_to_db(mind_id: str, identity: Any, db: Any) -> None:
    """Flush all relationships for a mind."""
    try:
        from sqlalchemy import text
        await db.execute(text("""
            DELETE FROM mind_relationships
            WHERE mind_id = (SELECT id FROM minds WHERE name = :name)
        """), {"name": mind_id})
        for agent_id, rel in identity.relationships.items():
            await db.execute(text("""
                INSERT INTO mind_relationships
                    (mind_id, agent_id, trust_level, interaction_count,
                     shared_projects, communication_style, notes, updated_at)
                VALUES
                    ((SELECT id FROM minds WHERE name = :name),
                     :agent_id, :trust, :count,
                     :projects, :style, :notes, :updated_at)
            """), {
                "name": mind_id,
                "agent_id": agent_id,
                "trust": float(getattr(rel, "trust_level", 0.5) or 0.5),
                "count": int(getattr(rel, "interaction_count", 0) or 0),
                "projects": json.dumps(list(getattr(rel, "shared_projects", []) or [])),
                "style": getattr(rel, "communication_style", None),
                "notes": getattr(rel, "notes", None),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        await db.commit()
    except Exception as e:
        log.debug("save_relationships_to_db failed: %s", e)


async def save_conversation_turn(
    mind_id: str,
    conversation_id: str,
    agent_id: Optional[str],
    turn_number: int,
    agent_message: str,
    mind_response: Any,
    db: Any,
) -> None:
    """Append one turn to the conversation log."""
    try:
        from sqlalchemy import text
        await db.execute(text("""
            INSERT INTO conversations
                (id, mind_id, agent_id, started_at, turn_count)
            VALUES
                (:conv_id,
                 (SELECT id FROM minds WHERE name = :name),
                 :agent_id, :started_at, :turn)
            ON CONFLICT (id) DO UPDATE SET
                turn_count = EXCLUDED.turn_count,
                ended_at   = NULL
        """), {
            "conv_id": conversation_id,
            "name": mind_id,
            "agent_id": agent_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "turn": turn_number,
        })
        await db.execute(text("""
            INSERT INTO conversation_turns
                (conversation_id, turn_number, agent_message, mind_response,
                 reasoning_trace, confidence)
            VALUES
                (:conv_id, :turn, :msg, :resp, :trace, :conf)
            ON CONFLICT (conversation_id, turn_number) DO NOTHING
        """), {
            "conv_id": conversation_id,
            "turn": turn_number,
            "msg": agent_message,
            "resp": json.dumps({
                "answer": getattr(mind_response, "answer", None),
                "clarifying_question": getattr(mind_response, "clarifying_question", None),
                "confidence": float(getattr(mind_response, "confidence", 0) or 0),
            }),
            "trace": json.dumps(
                mind_response.reasoning_trace.to_dict()
                if getattr(mind_response, "reasoning_trace", None)
                and hasattr(mind_response.reasoning_trace, "to_dict")
                else None
            ),
            "conf": float(getattr(mind_response, "confidence", 0) or 0),
        })
        await db.commit()
    except Exception as e:
        log.debug("save_conversation_turn failed: %s", e)


async def end_conversation_in_db(conversation_id: str, db: Any) -> None:
    """Mark a conversation as ended."""
    try:
        from sqlalchemy import text
        await db.execute(text("""
            UPDATE conversations
            SET ended_at = :ended_at
            WHERE id = :conv_id
        """), {
            "conv_id": conversation_id,
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.commit()
    except Exception as e:
        log.debug("end_conversation_in_db failed: %s", e)


async def load_conversation_history(mind_id: str, conversation_id: str, db: Any) -> List[Dict[str, Any]]:
    """Read the turn history for a conversation.  Used to rehydrate
    in-process state after a restart."""
    try:
        from sqlalchemy import text
        result = await db.execute(text("""
            SELECT turn_number, agent_message, mind_response, confidence
            FROM conversation_turns
            WHERE conversation_id = :conv_id
            ORDER BY turn_number
        """), {"conv_id": conversation_id})
        out: List[Dict[str, Any]] = []
        for row in result.fetchall():
            turn_num, msg, resp_json, conf = row
            # mind_response is stored as a JSON string
            if isinstance(resp_json, str):
                try:
                    resp_json = json.loads(resp_json)
                except (ValueError, TypeError):
                    resp_json = {}
            out.append({
                "turn_number": int(turn_num),
                "agent_message": msg,
                "response": resp_json if isinstance(resp_json, dict) else {},
                "confidence": float(conf or 0),
            })
        return out
    except Exception as e:
        log.debug("load_conversation_history failed: %s", e)
        return []


async def log_learning_event(
    mind_id: str,
    kind: str,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
    db: Any = None,
) -> None:
    """Append a learning event to the audit log."""
    try:
        from sqlalchemy import text
        await db.execute(text("""
            INSERT INTO mind_learning_events
                (mind_id, kind, description, metadata, source)
            VALUES
                ((SELECT id FROM minds WHERE name = :name),
                 :kind, :desc, :meta, :src)
        """), {
            "name": mind_id,
            "kind": kind,
            "desc": description,
            "meta": json.dumps(metadata or {}),
            "src": (metadata or {}).get("source", "interaction"),
        })
        await db.commit()
    except Exception as e:
        log.debug("log_learning_event failed: %s", e)


async def hydrate_mind(mind: Any, db: Any) -> None:
    """Load all persisted state into an in-process LivingMind.

    Reads identity, opinions, and relationships from the database
    and overwrites the in-process state.  Safe to call on startup.
    """
    try:
        from sqlalchemy import text
        # Ensure the mind row exists
        await ensure_mind_row(mind.mind_id, db)

        identity = await load_identity_from_db(mind.mind_id, db)
        if identity:
            if identity.get("core_traits"):
                mind.identity.core_traits = list(identity["core_traits"])
            if identity.get("capabilities"):
                mind.identity.capabilities = list(identity["capabilities"])
            if identity.get("limitations"):
                mind.identity.limitations = list(identity["limitations"])
            # Patterns are more complex (each is a LearnedPattern);
            # re-create them from the persisted dicts.
            from app.mind.identity import LearnedPattern
            mind.identity.learned_patterns = [
                LearnedPattern(
                    description=p["description"],
                    importance=p.get("importance", 0.5),
                    source=p.get("source", "interaction"),
                )
                for p in identity.get("learned_patterns", [])
            ]

        opinions = await load_opinions_from_db(mind.mind_id, db)
        if opinions:
            from app.mind.opinions import Opinion, Stance
            mind.opinions.opinions = {}
            for topic, data in opinions.items():
                try:
                    stance = Stance(data["stance"])
                except ValueError:
                    stance = Stance.NEUTRAL
                mind.opinions.opinions[topic] = Opinion(
                    topic=topic,
                    stance=stance,
                    strength=data["strength"],
                    rationale=data.get("rationale"),
                    evidence_count=data["evidence_count"],
                    memory_ids=data.get("memory_ids", []),
                )

        rels = await load_relationships_from_db(mind.mind_id, db)
        if rels:
            from app.mind.identity import Relationship
            mind.identity.relationships = {}
            for agent_id, data in rels.items():
                mind.identity.relationships[agent_id] = Relationship(
                    agent_id=agent_id,
                    trust_level=data["trust_level"],
                    interaction_count=data["interaction_count"],
                    shared_projects=data["shared_projects"],
                    communication_style=data.get("communication_style"),
                )

        log.info("hydrated mind '%s' from database", mind.mind_id)
    except Exception as e:
        log.warning("hydrate_mind failed: %s", e)


async def save_mind(mind: Any, db: Any) -> None:
    """Flush the full in-process state of a mind to the database."""
    await ensure_mind_row(mind.mind_id, db)
    await save_identity_to_db(mind.mind_id, mind.identity, db)
    await save_opinions_to_db(mind.mind_id, mind.opinions, db)
    await save_relationships_to_db(mind.mind_id, mind.identity, db)


__all__ = [
    "ensure_mind_row",
    "load_identity_from_db",
    "save_identity_to_db",
    "load_opinions_from_db",
    "save_opinions_to_db",
    "load_relationships_from_db",
    "save_relationships_to_db",
    "save_conversation_turn",
    "end_conversation_in_db",
    "load_conversation_history",
    "log_learning_event",
    "hydrate_mind",
    "save_mind",
]
