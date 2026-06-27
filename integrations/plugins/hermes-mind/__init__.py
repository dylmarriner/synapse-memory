"""Hermes + Living Mind integration.

This is a Python plugin for the Hermes agent framework.  It mirrors
the Claude Code plugin's hooks but uses Hermes's plugin system.

Install:
    cp -r integrations/plugins/hermes-mind ~/.hermes/hermes-agent/plugins/memory/mind
    # or use the plugin installer
    hermes plugin install /path/to/synapse-memory/integrations/plugins/hermes-mind

Configure (in ~/.hermes/config.yaml):
    plugins:
      mind:
        nexus_url: "http://localhost:7777"
        nexus_secret: "your-bearer-token"
        mind_id: "default"
        agent_id: "hermes"
"""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
import json
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexus.plugins.hermes_mind")

NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:7777").rstrip("/")
NEXUS_SECRET = os.environ.get("NEXUS_SECRET", "")
MIND_ID = os.environ.get("MIND_ID", "default")
AGENT_ID = os.environ.get("AGENT_ID", "hermes")


def _call(path: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not NEXUS_SECRET:
        return None
    headers = {
        "Authorization": f"Bearer {NEXUS_SECRET}",
        "Content-Type": "application/json",
    }
    method = "POST" if payload else "GET"
    data = json.dumps(payload).encode() if payload else None
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        log.debug("hermes_mind call failed: %s", e)
        return None


def on_session_start(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inject a Living Mind briefing at the start of every Hermes session.

    The returned dict is added to the agent's system prompt as
    additional context.
    """
    sections: List[str] = []

    identity = _call(f"/v1/mind/identity/{MIND_ID}")
    if identity and identity.get("description"):
        sections.append(identity["description"])

    think = _call("/v1/mind/think", {
        "mind_id": MIND_ID,
        "question": "What should I know right now?",
        "context": {"agent_id": AGENT_ID, "proactive_only": True},
    })
    if think and think.get("proactive_context"):
        lines = ["## Proactive Context (from the Living Mind)\n"]
        for item in think["proactive_context"][:5]:
            lines.append(
                f"- [{item['type']}] {item['content']} (relevance {item['relevance']:.2f})"
            )
        sections.append("\n".join(lines))

    opinions = _call(f"/v1/mind/opinions/{MIND_ID}")
    ops = opinions.get("opinions", {}) if opinions else {}
    if isinstance(ops, dict) and ops:
        lines = ["## Mind's Opinions\n"]
        for topic, op in list(ops.items())[:3]:
            if not op:
                continue
            lines.append(
                f"- **{topic}**: {op['stance']} (strength {op['strength']:.2f}, "
                f"{op['evidence_count']} pieces of evidence)"
            )
        sections.append("\n".join(lines))

    if not sections:
        return None
    return {"system_prompt_addition": "\n\n".join(sections)}


def on_prompt_submit(prompt: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inject just-in-time context from the Living Mind before each prompt."""
    think = _call("/v1/mind/think", {
        "mind_id": MIND_ID,
        "question": prompt[:500],
        "context": {"agent_id": AGENT_ID},
        "reasoning_depth": "fast",
    })
    if not think:
        return None
    sections: List[str] = []
    items = think.get("proactive_context") or []
    if items:
        lines = ["## Living Mind: Relevant Context\n"]
        for item in items[:3]:
            lines.append(
                f"- [{item['type']}] {item['content']} (relevance {item['relevance']:.2f})"
            )
        sections.append("\n".join(lines))
    if think.get("clarifying_question"):
        sections.append(
            f"## Living Mind: Clarifying Question\n{think['clarifying_question']}"
        )
    if not sections:
        return None
    return {"context_addition": "\n\n".join(sections)}


def on_session_end(session_summary: str, context: Dict[str, Any]) -> None:
    """Save a session summary so the next session has continuity."""
    _call("/v1/memory/save", {
        "content": f"Session with {AGENT_ID}: {session_summary[:500]}",
        "agent_id": AGENT_ID,
        "memory_type": "experience",
        "importance": 0.7,
        "tags": ["session_summary", AGENT_ID],
        "metadata": {"mind_id": MIND_ID, "source": "hermes_session_end"},
    })
