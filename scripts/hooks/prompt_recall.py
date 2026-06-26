#!/usr/bin/env python3
"""UserPromptSubmit hook — auto-recall relevant memories and activate pre-response reflection."""

import json
import os
import sys
import urllib.request

try:
    from nexus_hook_utils import append_session
except Exception:
    def append_session(*args, **kwargs): return None

NEXUS_URL = os.getenv("NEXUS_URL", "http://localhost:7777")
NEXUS_TOKEN = os.getenv("NEXUS_SECRET", "")
AGENT_ID = os.getenv("NEXUS_AGENT_ID", "claude-code")

# Quiet by default. Only the recall block below is injected, and only when a
# memory genuinely matches. No memory match → nothing injected (honest silence).
REFLECTION_NOTE = ""

# Only surface memories whose calibrated semantic relevance clears this bar.
MIN_RELEVANCE = float(os.getenv("NEXUS_RECALL_MIN_RELEVANCE", "0.55"))
MAX_RESULTS = int(os.getenv("NEXUS_RECALL_MAX_RESULTS", "3"))

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
        # Nothing worth recalling against — stay silent.
        sys.exit(0)

    append_session("user", user_prompt, {"hook": "UserPromptSubmit"})

    payload = json.dumps({
        "query": user_prompt[:500],
        "agent_id": AGENT_ID,
        "limit": MAX_RESULTS,
        "search_modes": ["vector", "lexical"],
        "min_relevance": MIN_RELEVANCE,
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
    results = data.get("results", [])[:MAX_RESULTS]

    # Honest silence: if nothing genuinely matched, inject nothing at all.
    if not results:
        sys.exit(0)

    lines = ["[NEXUS — you remember this from before:]"]
    for m in results:
        mtype = m.get("memory_type", "?")
        rel = m.get("relevance", 0) or 0
        confirmed = m.get("confirmed_count", 0) or 0
        contradicted = m.get("contradicted_count", 0) or 0
        # Surface trust so the model can weight what it recalls.
        trust = ""
        if confirmed or contradicted:
            trust = f" (confirmed {confirmed}×" + (f", contradicted {contradicted}×" if contradicted else "") + ")"
        content = m.get("content", "")[:300]
        lines.append(f"  [{mtype}|{rel:.0%} match{trust}] {content}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines),
        }
    }))

except Exception:
    # On any failure, stay silent rather than inject noise.
    sys.exit(0)
