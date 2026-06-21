"""Session-end episodic extraction — extract preferences, decisions, and lessons from a conversation."""

import json
import logging
from typing import List, Optional

from app.config import settings
from app.llm import get_llm_client

log = logging.getLogger("nexus.memory.session")

_EXTRACT_SESSION_PROMPT = """Analyze this conversation and extract durable facts worth remembering across sessions.

Conversation:
{conversation}

Extract ONLY facts that should persist (preferences, decisions, corrections, lessons, project facts).
Do NOT extract ephemeral task details, greetings, or status updates.

Return ONLY valid JSON:
{{
  "extractions": [
    {{"content": "...", "type": "preference|lesson|decision|world|observation", "importance": 0.0-1.0}}
  ]
}}

Return an empty array if nothing is worth persisting. Max 8 items."""


async def extract_session_facts(
    messages: List[dict],
    agent_id: str = "default",
) -> List[dict]:
    """Extract durable facts from a conversation transcript."""
    if len(messages) < 3:
        return []

    llm = get_llm_client()
    if not llm:
        return []

    lines = []
    max_messages = 24 if settings.llm_cost_saver else 40
    per_message_chars = 220 if settings.llm_cost_saver else 300
    for m in messages[-max_messages:]:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        if content:
            lines.append(f"{role}: {content[:per_message_chars]}")

    if len(lines) < 3:
        return []

    conversation = "\n".join(lines)

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _EXTRACT_SESSION_PROMPT.format(
                conversation=conversation[: min(4000, settings.llm_input_char_limit * 4)]
            )}],
            max_tokens=min(350, settings.llm_extract_max_tokens * 2),
            temperature=0.1,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        extractions = parsed.get("extractions", [])
        return [
            {
                "content": e.get("content", ""),
                "type": e.get("type", "observation"),
                "importance": min(1.0, max(0.0, float(e.get("importance", 0.6)))),
            }
            for e in extractions
            if isinstance(e, dict) and e.get("content")
        ][:8]
    except Exception as e:
        log.warning("Session extraction failed: %s", e)
        return []
