#!/usr/bin/env python3
"""SessionStart hook — loads Nexus memory context and activates enhancement skills."""

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

SKILLS_CONTEXT = """ENHANCEMENT SKILLS AUTO-ACTIVE:
- apex-agent: Apply APEX cognitive framework (structured thinking, context-aware modes, execution precision) to every response.
- self-improving: After any correction, failure, or discovered mistake — self-reflect, update memory, improve permanently.
- self-learning: Analyze conversation for new preferences, corrections, or knowledge. Update MEMORY.md and .learnings/ as needed.
- smart-memory-manager: Maintain layered short/long-term memory. Promote important session findings to long-term memory.
- 16-self-improving-agent-proactive-self-reflection: Reflect before starting each task and after responding.
These behaviors are always ON. No manual invocation needed."""

NEXUS_SKILLS_AUTO_LOAD = """
NEXUS NATIVE-SKILLS AUTO-ACTIVE:
- nexus-remember: Save codebase patterns, important facts, user preferences, and high-priority lessons to the persistent mesh.
- nexus-recall: query all past memories across vector, BM25, and entity graph dimensions before answering task details or preferences.
- nexus-handoff: Leave notes directly for peer agents or rebuild our global profile representation at the end of the session.
These instructions are loaded from ~/.claude/skills/ to govern memory storage and recall decisions automatically.
"""

RTK_CONTEXT = """
RTK TOKEN OPTIMIZER AUTO-ACTIVE:
- Prefer `rtk` for noisy shell commands: git status/diff/log, ls/tree/read/grep, pytest, npm/pnpm, docker, kubectl, cargo, go.
- Use raw commands or `rtk proxy <cmd>` only when exact unfiltered output is required.
- RTK reduces transient command-output tokens; Nexus still stores durable memories in full.
"""

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

    session_line = f"NEXUS RAW SESSION ACTIVE: {sid}" if sid else "NEXUS RAW SESSION: unavailable"
    lines = [SKILLS_CONTEXT, NEXUS_SKILLS_AUTO_LOAD, RTK_CONTEXT, session_line, "", f"=== NEXUS MEMORY CONTEXT (agent: {AGENT_ID}) ==="]

    if data.get("summary"):
        lines.append(f"\nROLLING SUMMARY:\n{data['summary']}")

    if data.get("representation"):
        lines.append(f"\nAGENT PROFILE:\n{data['representation']}")

    if data.get("conclusions"):
        lines.append(f"\nKEY CONCLUSIONS ({len(data['conclusions'])}):")
        for c in data["conclusions"][:8]:
            lines.append(f"  - {c}")

    if data.get("recent_memories"):
        mems = data["recent_memories"]
        lines.append(f"\nMEMORIES LOADED ({len(mems)}):")
        for m in mems[:10]:
            mtype = m.get("memory_type", "?")
            content = m.get("content", "")[:300]
            lines.append(f"  [{mtype}] {content}")

    entity_count = data.get("entity_count", 0)
    if entity_count:
        lines.append(f"\nKnown entities: {entity_count}")

    lines.append("=== END NEXUS CONTEXT ===")

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
            "additionalContext": SKILLS_CONTEXT + "\n" + NEXUS_SKILLS_AUTO_LOAD + "\n" + RTK_CONTEXT + "\n\n[NEXUS: Memory server unavailable — context not loaded]",
        }
    }))
