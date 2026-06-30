"""Living Mind REST API.

Mounted at `/v1/mind/*` by `app/main.py`.  Every endpoint is a
thin adapter over a Living Mind instance — the heavy lifting
lives in `app/mind/living_mind.py`.

Endpoints:
    POST /v1/mind/think                       — ask the mind a question
    POST /v1/mind/reflect                     — deep reflection on a topic
    POST /v1/mind/conversations/start         — begin a multi-turn dialogue
    POST /v1/mind/conversations/{id}/turn     — send a turn
    POST /v1/mind/conversations/{id}/end      — end the dialogue, extract learnings
    GET  /v1/mind/identity/{mind_id}         — get the mind's self-model
    GET  /v1/mind/opinions/{mind_id}          — get the mind's opinions
    GET  /v1/mind/registry                    — list available minds

In-process minds are cached by `mind_id` for the lifetime of the
process.  This is fine for a single-tenant deployment; for
multi-tenant, the registry lives in the database and a per-request
mind is constructed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.mind import (
    LivingMind,
    MindConfig,
    ReasoningDepth,
    MindResponse,
)
from app.mind.store import InMemoryMindStore
from app.mind.conversation import ConversationManager

log = logging.getLogger("nexus.routers.mind")
router = APIRouter(prefix="/v1/mind", tags=["mind"])


# In-process mind registry.  Keyed by mind_id.  A real deployment
# hydrates from the database on first use.
_MINDS: Dict[str, LivingMind] = {}


def _get_mind(mind_id: str) -> LivingMind:
    """Return the mind for `mind_id`, creating it on first use.

    On first access, the mind is created in-process and
    asynchronously hydrated from the database (if available).
    The hydration runs in the background; the returned mind
    serves from in-process state immediately so the first call
    is fast.
    """
    if mind_id not in _MINDS:
        # Use the real Nexus memory store when the DB is available;
        # fall back to the in-memory store otherwise (tests, embedded).
        try:
            from app.db import SessionLocal
            from app.mind.store import NexusMemoryStore
            store = NexusMemoryStore(db_session_factory=SessionLocal)
            log.debug("mind '%s' using NexusMemoryStore", mind_id)
        except Exception:
            store = InMemoryMindStore()
            log.debug("mind '%s' using InMemoryMindStore", mind_id)
        from app.config import settings as _settings
        mind = LivingMind(
            mind_id=mind_id,
            config=MindConfig(
                llm_model=_settings.mind_llm_model,
                fallback_llm_model=_settings.mind_fallback_model,
                enable_extract=_settings.mind_enable_extract,
                enable_verify=_settings.mind_enable_verify,
                enable_llm_proactive=_settings.mind_enable_llm_proactive,
                enable_llm_opinion=_settings.mind_enable_llm_opinion,
                enable_related_graph=_settings.mind_enable_related_graph,
            ),
            memory_store=store,
        )
        # Primary reasoning LLM: local Ollama (fast, on-GPU, no API cost).
        try:
            import os
            from app.llm import get_ollama_client
            ollama_url = os.environ.get("OLLAMA_BASE_URL", _settings.ollama_base_url)
            mind.llm = get_ollama_client(base_url=ollama_url, model=_settings.mind_llm_model)
            mind.reasoning.llm = mind.llm
            log.info("mind '%s' primary LLM: Ollama %s via %s",
                     mind_id, _settings.mind_llm_model, ollama_url)
        except Exception as e:
            log.debug("mind '%s' Ollama primary unavailable: %s", mind_id, e)
        # Fallback reasoning LLM: DeepSeek (used when the local call fails or
        # returns nothing).  None if no DeepSeek/OpenAI key is configured.
        try:
            from app.llm import get_llm_client
            mind.llm_fallback = get_llm_client()
            if mind.llm_fallback is not None:
                log.info("mind '%s' fallback LLM: %s", mind_id, _settings.mind_fallback_model)
            if mind.llm is None:
                # No local model — promote the fallback to primary so reasoning
                # still gets LLM enrichment.
                mind.llm = mind.llm_fallback
                mind.reasoning.llm = mind.llm
                mind.config.llm_model = _settings.mind_fallback_model
        except Exception as e:
            log.debug("mind '%s' fallback LLM unavailable: %s", mind_id, e)
        if mind.llm is None:
            log.debug("mind '%s' running deterministic (no LLM available)", mind_id)
        # Wire the conversation manager to the DB if SessionLocal
        # is available — so turns are persisted.
        try:
            from app.db import SessionLocal
            mind.conversations = ConversationManager(
                mind_id=mind_id, mind=mind, db_session_factory=SessionLocal,
            )
        except Exception:
            pass
        _MINDS[mind_id] = mind
        log.info("created in-process living mind '%s'", mind_id)
        # Asynchronously hydrate from the database.  We don't
        # await it — the first call doesn't need DB state.
        try:
            import asyncio
            from app.db import SessionLocal
            from app.mind import persist as _persist

            async def _hydrate():
                try:
                    async with SessionLocal() as db:
                        await _persist.hydrate_mind(mind, db)
                except Exception as e:
                    log.debug("hydration failed: %s", e)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(_hydrate())
                else:
                    loop.run_until_complete(_hydrate())
            except RuntimeError:
                # No event loop — skip hydration
                pass
        except ImportError:
            pass
    return _MINDS[mind_id]


async def _save_mind_state(mind_id: str) -> None:
    """Flush the in-process state of a mind to the database.

    Called at session end (and can be called periodically).
    """
    mind = _MINDS.get(mind_id)
    if mind is None:
        return
    try:
        from app.db import SessionLocal
        from app.mind import persist as _persist
        async with SessionLocal() as db:
            await _persist.save_mind(mind, db)
    except Exception as e:
        log.debug("save_mind_state failed: %s", e)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ThinkRequest(BaseModel):
    mind_id: str = Field(default="default")
    question: str
    context: Optional[Dict[str, Any]] = None
    reasoning_depth: Optional[str] = None     # "fast" | "standard" | "deep"


class ThinkResponse(BaseModel):
    answer: Optional[str] = None
    clarifying_question: Optional[str] = None
    confidence: float = 0.0
    memories_cited: List[Any] = Field(default_factory=list)
    proactive_context: List[Dict[str, Any]] = Field(default_factory=list)
    opinions_expressed: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_trace: Optional[Dict[str, Any]] = None
    code_symbols: List[Dict[str, Any]] = Field(default_factory=list)  # code-context symbols used by the mind


class ReflectRequest(BaseModel):
    mind_id: str = Field(default="default")
    topic: str
    depth: str = "mid"                        # "low" | "mid" | "high"


class StartConversationRequest(BaseModel):
    mind_id: str = Field(default="default")
    agent_id: str = "agent"


class ConversationTurnRequest(BaseModel):
    mind_id: str = Field(default="default")
    message: str


class EndConversationRequest(BaseModel):
    mind_id: str = Field(default="default")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/think", response_model=ThinkResponse)
async def think(
    body: ThinkRequest,
    fmt: str = Query("json", pattern="^(json|compact)$"),
):
    """Ask the living mind a question and get a reasoned response.

    Add `?fmt=compact` to get the MUNCH-encoded memories_cited list
    (path-interned, CSV-tagged).  The answer/opinions/proactive blocks
    are kept as JSON since they're not list-heavy.
    """
    mind = _get_mind(body.mind_id)
    response = await mind.think(
        question=body.question,
        context=body.context or {},
        reasoning_depth=body.reasoning_depth,
    )
    result = _mind_response_to_dict(response)
    if fmt == "compact":
        from app.code.munch import encode_records
        cited = result.get("memories_cited", [])
        if cited:
            result["memories_cited_munch"] = encode_records(
                [{"id": m.get("id", ""), "content": m.get("content", "")[:300]} for m in cited],
                ["id", "content"],
            )
    return result


@router.post("/reflect", response_model=ThinkResponse)
async def reflect(
    body: ReflectRequest,
    fmt: str = Query("json", pattern="^(json|compact)$"),
):
    """Deep reflection on a topic.  Synthesises many memories into a
    single coherent narrative."""
    mind = _get_mind(body.mind_id)
    response = await mind.reflect(topic=body.topic, depth=body.depth)
    return _mind_response_to_dict(response)


@router.post("/conversations/start")
async def start_conversation(body: StartConversationRequest):
    """Start a multi-turn conversation with the mind."""
    mind = _get_mind(body.mind_id)
    conv_id = mind.conversations.start_conversation(body.agent_id)
    return {"conversation_id": conv_id, "mind_id": body.mind_id, "agent_id": body.agent_id}


@router.post("/conversations/{conversation_id}/turn", response_model=ThinkResponse)
async def conversation_turn(conversation_id: str, body: ConversationTurnRequest):
    """Send a turn in an ongoing conversation."""
    mind = _get_mind(body.mind_id)
    try:
        response = await mind.conversations.process_turn(conversation_id, body.message)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown conversation_id: {conversation_id}")
    return _mind_response_to_dict(response)


@router.post("/conversations/{conversation_id}/end")
async def end_conversation(conversation_id: str, body: EndConversationRequest):
    """End a conversation and extract learnings."""
    mind = _get_mind(body.mind_id)
    try:
        result = await mind.conversations.end_conversation(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown conversation_id: {conversation_id}")
    # A conversation end is a natural checkpoint: flush the mind's evolved
    # identity, opinions, and relationships to the database so they survive
    # a restart (the design goal — conversation state is durable, not in-RAM).
    await _save_mind_state(body.mind_id)
    return result


@router.get("/proactive")
async def proactive(
    mind_id: str = "default",
    agent_id: Optional[str] = Query(None),
    question: Optional[str] = Query(None),
):
    """Surface the mind's proactive context for an agent, without being asked
    a specific question.  Returns the items the mind thinks the agent should
    know about right now (unfinished promises, recent work, contradictions,
    time-sensitive notes, relationship insights)."""
    mind = _get_mind(mind_id)
    memories = await mind._retrieve_memories(question or "", {"agent_id": agent_id})
    items = await mind.proactive.identify_context(
        question=question or "",
        memories=memories,
        agent_id=agent_id,
    )
    return {
        "mind_id": mind_id,
        "agent_id": agent_id,
        "proactive_context": [item.to_dict() for item in items],
    }


@router.get("/identity/{mind_id}")
async def get_identity(mind_id: str):
    """Get the mind's current self-model."""
    mind = _get_mind(mind_id)
    return {
        "mind_id": mind.mind_id,
        "description": mind.get_self_description(),
        "identity": mind.identity.to_dict(),
    }


@router.get("/opinions/{mind_id}")
async def get_opinions(mind_id: str, topic: Optional[str] = Query(None)):
    """Get the mind's opinions.  Optional `topic` filter."""
    mind = _get_mind(mind_id)
    if topic:
        opinion = mind.opinions.get(topic)
        if opinion is None:
            return {"mind_id": mind_id, "topic": topic, "opinion": None}
        return {"mind_id": mind_id, "topic": topic, "opinion": opinion.to_dict()}
    return {
        "mind_id": mind_id,
        "opinions": {t: o.to_dict() for t, o in mind.opinions.opinions.items()},
    }


@router.get("/conversations")
async def list_conversations(
    mind_id: str = "default",
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Every conversation the mind has had — full transparency over dialogue.

    Reads the persisted `conversations` archive (newest first), joined to the
    agent name.  Each row carries turn_count, open/closed state, and summary.
    """
    rows = (await db.execute(text("""
        SELECT c.id, COALESCE(a.name, '—') AS agent_name,
               c.started_at, c.ended_at, c.turn_count, c.summary
        FROM conversations c
        LEFT JOIN agents a ON a.id = c.agent_id
        WHERE c.mind_id = (SELECT id FROM minds WHERE name = :mind_name)
        ORDER BY c.started_at DESC
        LIMIT :limit
    """), {"mind_name": mind_id, "limit": limit})).fetchall()
    return {
        "mind_id": mind_id,
        "conversations": [
            {
                "id": str(r.id),
                "agent_id": r.agent_name,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "turn_count": int(r.turn_count or 0),
                "open": r.ended_at is None,
                "summary": r.summary,
            }
            for r in rows
        ],
    }


@router.get("/conversations/{conversation_id}/turns")
async def conversation_turns_history(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Every turn of one conversation — each agent message and the mind's
    full response, confidence, and reasoning trace.  This is where a single
    'thought' is fully visible end to end."""
    rows = (await db.execute(text("""
        SELECT turn_number, agent_message, mind_response, reasoning_trace, confidence, created_at
        FROM conversation_turns
        WHERE conversation_id = CAST(:cid AS uuid)
        ORDER BY turn_number ASC
    """), {"cid": conversation_id})).fetchall()
    return {
        "conversation_id": conversation_id,
        "turns": [
            {
                "turn_number": int(r.turn_number),
                "agent_message": r.agent_message,
                "mind_response": r.mind_response,
                "reasoning_trace": r.reasoning_trace,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/learning-events")
async def learning_events(
    mind_id: str = "default",
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Every learning the mind has extracted — its stream of 'thoughts':
    patterns, capabilities, limitations, opinions formed, identity updates."""
    rows = (await db.execute(text("""
        SELECT kind, description, source, metadata, created_at
        FROM mind_learning_events
        WHERE mind_id = (SELECT id FROM minds WHERE name = :mind_name)
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"mind_name": mind_id, "limit": limit})).fetchall()
    return {
        "mind_id": mind_id,
        "events": [
            {
                "kind": r.kind,
                "description": r.description,
                "source": r.source,
                "metadata": r.metadata,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/proactive-log")
async def proactive_log(
    mind_id: str = "default",
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Every item the mind has proactively surfaced, with its relevance —
    the record of what the mind volunteered without being asked."""
    rows = (await db.execute(text("""
        SELECT p.item_type, p.content, p.relevance, p.used, p.created_at,
               COALESCE(a.name, '—') AS agent_name
        FROM mind_proactive_log p
        LEFT JOIN agents a ON a.id = p.agent_id
        WHERE p.mind_id = (SELECT id FROM minds WHERE name = :mind_name)
        ORDER BY p.created_at DESC
        LIMIT :limit
    """), {"mind_name": mind_id, "limit": limit})).fetchall()
    return {
        "mind_id": mind_id,
        "items": [
            {
                "item_type": r.item_type,
                "content": r.content,
                "relevance": float(r.relevance or 0),
                "used": bool(r.used),
                "agent_id": r.agent_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/registry")
async def registry():
    """List all in-process minds."""
    return {
        "minds": [
            {
                "mind_id": m.mind_id,
                "patterns_learned": len(m.identity.learned_patterns),
                "capabilities": len(m.identity.capabilities),
                "relationships": len(m.identity.relationships),
                "opinions_held": len(m.opinions.opinions),
            }
            for m in _MINDS.values()
        ],
        "total": len(_MINDS),
    }


@router.get("/dashboard")
async def dashboard(mind_id: str = "default"):
    """A single-screen dashboard of one mind's state.

    Returns everything an operator would want to see on one page:
    identity summary, learned patterns, capabilities, limitations,
    active opinions, relationships, and recent activity.  Designed
    for a future HTML dashboard.
    """
    mind = _get_mind(mind_id)
    identity = mind.identity.to_dict()
    opinions = mind.opinions.opinions
    return {
        "mind_id": mind.mind_id,
        "self_description": mind.get_self_description(),
        "identity": identity,
        "opinions": {
            topic: op.to_dict() for topic, op in opinions.items()
        },
        # `identity["relationships"]` is already serialised to plain dicts
        # by Identity.to_dict() — pass it through as-is.
        "relationships": identity["relationships"],
        "stats": {
            "patterns_learned": len(identity["learned_patterns"]),
            "capabilities": len(identity["capabilities"]),
            "limitations": len(identity["limitations"]),
            "opinions_held": len(opinions),
            "relationships": len(identity["relationships"]),
            "active_conversations": len(mind.conversations.active),
        },
        "config": mind.config.__dict__ if hasattr(mind.config, "__dict__") else {},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mind_response_to_dict(response: MindResponse) -> Dict[str, Any]:
    """Convert a MindResponse to the API shape."""
    import logging
    log = logging.getLogger("nexus.routers.mind")
    log.info("router._mind_response_to_dict: code_symbols=%d", len(response.code_symbols or []))
    return {
        "answer": response.answer,
        "clarifying_question": response.clarifying_question,
        "reasoning_trace": response.reasoning_trace.to_dict() if response.reasoning_trace else None,
        "confidence": response.confidence,
        "proactive_context": [item.to_dict() for item in response.proactive_context],
        "memories_cited": response.memories_cited,
        "opinions_expressed": [op.to_dict() for op in response.opinions_expressed],
        "code_symbols": response.code_symbols,
    }
