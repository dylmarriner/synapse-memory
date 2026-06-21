#!/usr/bin/env python3
"""SessionStart hook — loads Nexus memory context and activates enhancement skills."""

import json
import os
import sys
import urllib.request

NEXUS_URL = os.getenv("NEXUS_URL", "http://localhost:7777")
NEXUS_TOKEN = os.getenv("NEXUS_SECRET", "")
AGENT_ID = os.getenv("NEXUS_AGENT_ID", "claude-code")

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

try:
    req = urllib.request.Request(
        f"{NEXUS_URL}/v1/agents/{AGENT_ID}/context",
        headers={"Authorization": f"Bearer {NEXUS_TOKEN}"}
    )
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())

    lines = [SKILLS_CONTEXT, NEXUS_SKILLS_AUTO_LOAD, "", f"=== NEXUS MEMORY CONTEXT (agent: {AGENT_ID}) ==="]

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
            "additionalContext": SKILLS_CONTEXT + "\n" + NEXUS_SKILLS_AUTO_LOAD + "\n\n[NEXUS: Memory server unavailable — context not loaded]",
        }
    }))
