#!/usr/bin/env python3
"""UserPromptSubmit hook — auto-recall relevant memories and activate pre-response reflection."""

import json
import os
import sys
import urllib.request

NEXUS_URL = os.getenv("NEXUS_URL", "http://localhost:7777")
NEXUS_TOKEN = os.getenv("NEXUS_SECRET", "")
AGENT_ID = os.getenv("NEXUS_AGENT_ID", "claude-code")

REFLECTION_NOTE = "[PRE-RESPONSE: apex-agent + self-reflection active] Engage structured thinking before responding: consider accuracy, completeness, edge cases, and what you may not know."

try:
    raw = sys.stdin.read()
    if raw.strip():
        stdin_data = json.loads(raw)
        user_prompt = (
            stdin_data.get("userPrompt", "") or
            stdin_data.get("prompt", "") or
            stdin_data.get("message", "") or ""
        )
    else:
        user_prompt = ""

    if not user_prompt or len(user_prompt.strip()) < 8:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": REFLECTION_NOTE,
            }
        }))
        sys.exit(0)

    payload = json.dumps({
        "query": user_prompt[:500],
        "agent_id": AGENT_ID,
        "limit": 5,
        "search_modes": ["vector", "lexical"],
    }).encode()

    req = urllib.request.Request(
        f"{NEXUS_URL}/v1/memory/recall",
        data=payload,
        headers={
            "Authorization": f"Bearer {NEXUS_TOKEN}",
            "Content-Type": "application/json",
        }
    )
    resp = urllib.request.urlopen(req, timeout=4)
    data = json.loads(resp.read())
    results = data.get("results", [])

    lines = [REFLECTION_NOTE]
    if results:
        lines.append("")
        lines.append("[NEXUS AUTO-RECALL — relevant memories:]")
        for m in results:
            mtype = m.get("memory_type", "?")
            score = m.get("score", 0)
            content = m.get("content", "")[:300]
            lines.append(f"  [{mtype}|{score:.2f}] {content}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines),
        }
    }))

except Exception:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": REFLECTION_NOTE,
        }
    }))
