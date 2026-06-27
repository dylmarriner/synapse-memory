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

from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, Field

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
        store = InMemoryMindStore()
        mind = LivingMind(
            mind_id=mind_id,
            config=MindConfig(),
            memory_store=store,
        )
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
    memories_cited: List[str] = Field(default_factory=list)
    proactive_context: List[Dict[str, Any]] = Field(default_factory=list)
    opinions_expressed: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_trace: Optional[Dict[str, Any]] = None


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
async def think(body: ThinkRequest):
    """Ask the living mind a question and get a reasoned response."""
    mind = _get_mind(body.mind_id)
    response = await mind.think(
        question=body.question,
        context=body.context or {},
        reasoning_depth=body.reasoning_depth,
    )
    return _mind_response_to_dict(response)


@router.post("/reflect", response_model=ThinkResponse)
async def reflect(body: ReflectRequest):
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
    return result


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
        "relationships": {
            agent_id: rel.to_dict()
            for agent_id, rel in identity["relationships"].items()
        },
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
    return {
        "answer": response.answer,
        "clarifying_question": response.clarifying_question,
        "confidence": response.confidence,
        "memories_cited": response.memories_cited,
        "proactive_context": [item.to_dict() for item in response.proactive_context],
        "opinions_expressed": [op.to_dict() for op in response.opinions_expressed],
        "reasoning_trace": response.reasoning_trace.to_dict() if response.reasoning_trace else None,
    }
