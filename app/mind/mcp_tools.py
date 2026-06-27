"""MCP tools for the Living Mind.

These are added to the existing Nexus MCP server alongside the
existing memory tools.  Agents that speak MCP get a `mind_*` tool
prefix that maps to the Living Mind REST API.

The tools mirror the REST endpoints one-to-one.  An agent can:

  - mind_think           — ask the mind a question
  - mind_reflect         — deep reflection on a topic
  - mind_start_conversation — begin a multi-turn dialogue
  - mind_conversation_turn  — send a turn in an ongoing dialogue
  - mind_end_conversation   — end a dialogue
  - mind_get_identity    — get the mind's self-model
  - mind_get_opinions    — get the mind's opinions
  - mind_get_proactive    — get proactive context

When the agent calls any `memory_*` tool, the active-memory layer
routes it through the Mind so the agent doesn't need to know the
Mind exists.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.mind.mcp")


# These wrappers are added to the existing MCP router in `app/mcp.py`.
# They translate the MCP tool-call shape into a REST call against
# the mind router, which is mounted at `/v1/mind/*`.

async def mind_think(
    question: str,
    mind_id: str = "default",
    context: Optional[Dict[str, Any]] = None,
    reasoning_depth: Optional[str] = None,
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: ask the living mind a question."""
    import httpx
    payload = {
        "mind_id": mind_id,
        "question": question,
        "context": context or {},
    }
    if reasoning_depth:
        payload["reasoning_depth"] = reasoning_depth
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{base_url}/v1/mind/think", json=payload)
        r.raise_for_status()
        return r.json()


async def mind_reflect(
    topic: str,
    mind_id: str = "default",
    depth: str = "mid",
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: deep reflection on a topic."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{base_url}/v1/mind/reflect", json={
            "mind_id": mind_id,
            "topic": topic,
            "depth": depth,
        })
        r.raise_for_status()
        return r.json()


async def mind_start_conversation(
    agent_id: str,
    mind_id: str = "default",
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: start a multi-turn conversation with the mind."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{base_url}/v1/mind/conversations/start", json={
            "mind_id": mind_id,
            "agent_id": agent_id,
        })
        r.raise_for_status()
        return r.json()


async def mind_conversation_turn(
    conversation_id: str,
    message: str,
    mind_id: str = "default",
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: send a turn in an ongoing conversation."""
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{base_url}/v1/mind/conversations/{conversation_id}/turn",
            json={"mind_id": mind_id, "message": message},
        )
        r.raise_for_status()
        return r.json()


async def mind_end_conversation(
    conversation_id: str,
    mind_id: str = "default",
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: end a conversation and extract learnings."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{base_url}/v1/mind/conversations/{conversation_id}/end",
            json={"mind_id": mind_id},
        )
        r.raise_for_status()
        return r.json()


async def mind_get_identity(
    mind_id: str = "default",
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: get the mind's current self-model."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{base_url}/v1/mind/identity/{mind_id}")
        r.raise_for_status()
        return r.json()


async def mind_get_opinions(
    mind_id: str = "default",
    topic: Optional[str] = None,
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: get the mind's opinions."""
    import httpx
    url = f"{base_url}/v1/mind/opinions/{mind_id}"
    if topic:
        url += f"?topic={topic}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def mind_get_proactive(
    mind_id: str = "default",
    agent_id: str = "agent",
    question: Optional[str] = None,
    base_url: str = "http://localhost:7777",
) -> Dict[str, Any]:
    """MCP tool: get proactive context the mind thinks is relevant."""
    import httpx
    # Use the think endpoint with empty question to get proactive
    payload = {
        "mind_id": mind_id,
        "question": question or "What should I know right now?",
        "context": {"agent_id": agent_id, "proactive_only": True},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{base_url}/v1/mind/think", json=payload)
        r.raise_for_status()
        body = r.json()
        return {
            "proactive_items": body.get("proactive_context", []),
            "answer": body.get("answer"),
        }


# Tool definitions — these are added to the MCP server's tool list.
MIND_MCP_TOOLS = [
    {
        "name": "mind_think",
        "description": (
            "Ask the living mind a question and get a reasoned response. "
            "The mind retrieves relevant memories, reasons about them, "
            "forms opinions, and proactively surfaces context. "
            "Use this when you need context, an explanation, or a "
            "thoughtful opinion about something the mind has seen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the mind."},
                "mind_id": {"type": "string", "default": "default", "description": "Which mind to query."},
                "context": {"type": "object", "description": "Optional context (agent_id, conversation_id, etc.)."},
                "reasoning_depth": {"type": "string", "enum": ["fast", "standard", "deep"], "description": "How much reasoning effort to apply."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "mind_reflect",
        "description": "Ask the mind to reflect deeply on a topic. Synthesises many memories into a single coherent narrative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The topic to reflect on."},
                "mind_id": {"type": "string", "default": "default"},
                "depth": {"type": "string", "enum": ["low", "mid", "high"], "default": "mid"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "mind_start_conversation",
        "description": "Start a multi-turn conversation with the mind. Returns a conversation_id to use for subsequent turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent starting the conversation."},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "mind_conversation_turn",
        "description": "Send a message in an ongoing conversation with the mind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "message": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["conversation_id", "message"],
        },
    },
    {
        "name": "mind_end_conversation",
        "description": "End a conversation with the mind and extract learnings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "mind_get_identity",
        "description": "Get the mind's current self-model — its core traits, learned patterns, capabilities, and limitations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
            },
        },
    },
    {
        "name": "mind_get_opinions",
        "description": "Get the mind's opinions on topics. Returns stance, strength, and evidence count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
                "topic": {"type": "string", "description": "Optional specific topic."},
            },
        },
    },
    {
        "name": "mind_get_proactive",
        "description": "Get proactive context the mind thinks is relevant right now — unfinished promises, recent related work, contradictions, patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
                "agent_id": {"type": "string", "default": "agent"},
                "question": {"type": "string", "description": "Optional question to focus the proactive context."},
            },
        },
    },
]


__all__ = [
    "mind_think", "mind_reflect", "mind_start_conversation",
    "mind_conversation_turn", "mind_end_conversation",
    "mind_get_identity", "mind_get_opinions", "mind_get_proactive",
    "MIND_MCP_TOOLS",
]
