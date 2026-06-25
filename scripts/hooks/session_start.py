#!/usr/bin/env python3
"""SessionStart hook — loads lightweight Nexus identity context (no memory dump)."""

import json
import os
import sys
import urllib.request
from pathlib import Path

try:
    from nexus_hook_utils import AGENT_ID, PROJECT_KEY, append_session, start_session
except Exception:
    AGENT_ID = os.getenv("NEXUS_AGENT_ID", "claude-code")
    PROJECT_KEY = os.getenv("NEXUS_PROJECT_KEY") or Path.cwd().name
    def start_session(*args, **kwargs): return None
    def append_session(*args, **kwargs): return None

NEXUS_URL = os.getenv("NEXUS_URL", "http://localhost:7777")
NEXUS_TOKEN = os.getenv("NEXUS_SECRET", "")
AGENT_ID = os.getenv("NEXUS_AGENT_ID", AGENT_ID)

SKILLS_CONTEXT = """MEMORY SKILLS AUTO-ACTIVE:
- nexus-remember: Save codebase patterns, important facts, user preferences, and high-priority lessons to Nexus.
- nexus-recall: Query Nexus (vector + BM25 + graph) before answering questions about past decisions, preferences, or prior work.
- nexus-handoff: Leave notes for peer agents or rebuild the agent profile at the end of the session.
RTK: prefer `rtk` for noisy shell commands to reduce token usage (git, ls, grep, pytest, docker, etc.)."""

try:
    sid = start_session(title=f"{AGENT_ID} session in {PROJECT_KEY}", metadata={"hook": "SessionStart"})
    if sid:
        append_session("system", f"SessionStart hook initialized Nexus session {sid} for agent {AGENT_ID} in project {PROJECT_KEY}.", {"hook": "SessionStart"})

    req = urllib.request.Request(
        f"{NEXUS_URL}/v1/agents/{AGENT_ID}/context",
        headers={"Authorization": f"Bearer {NEXUS_TOKEN}"}
    )
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())

    lines = [SKILLS_CONTEXT, "", f"=== NEXUS IDENTITY (agent: {AGENT_ID}) ==="]

    # Rolling summary — the most useful compressed history of who this agent is
    if data.get("summary"):
        lines.append(f"\nSUMMARY:\n{data['summary']}")

    # Agent representation — LLM-generated profile
    if data.get("representation"):
        lines.append(f"\nPROFILE:\n{data['representation']}")

    # Conclusions / preferences — these are explicit rules to follow
    if data.get("conclusions"):
        lines.append(f"\nKEY RULES ({len(data['conclusions'])}):")
        for c in data["conclusions"][:5]:
            lines.append(f"  - {c}")

    entity_count = data.get("entity_count", 0)
    if entity_count:
        lines.append(f"\nKnown entities: {entity_count} (use nexus-recall to search)")

    lines.append("\nMemories are recalled on-demand via nexus-recall. Do not ask for a memory dump.")
    lines.append("=== END NEXUS IDENTITY ===")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))

except Exception:
    # Nexus unavailable — still activate skills
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": SKILLS_CONTEXT + "\n\n[NEXUS: Memory server unavailable — context not loaded]",
        }
    }))
