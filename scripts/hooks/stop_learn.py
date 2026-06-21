#!/usr/bin/env python3
"""Stop hook — self-improvement + Nexus lesson-saving cycle."""

import json
import sys

try:
    from nexus_hook_utils import append_session
except Exception:
    def append_session(*args, **kwargs): return None

try:
    raw = sys.stdin.read()
    hook_input = json.loads(raw) if raw.strip() else {}
except Exception:
    hook_input = {}

stop_event = {
    "hook": "Stop",
    "stop_hook_active": True,
}
for key in ("transcript_path", "cwd", "session_id"):
    if hook_input.get(key):
        stop_event[key] = hook_input[key]

append_session(
    "event",
    "Stop hook executed. Agent should save durable lessons/preferences/facts if any were learned in the response.",
    stop_event,
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": (
            "[POST-RESPONSE: self-improving + self-learning + Nexus cycle]\n"
            "Check the following:\n"
            "1. Were corrections given or mistakes made? → Use memory_save_lesson MCP tool to permanently save the lesson.\n"
            "2. New user preferences revealed? → Use memory_save MCP tool (memory_type=preference).\n"
            "3. Important facts or project context learned? → Use memory_save (memory_type=world or experience).\n"
            "4. Should ALL agents know this? → Use memory_save_global.\n"
            "5. Did a shell command produce noisy output? → Prefer RTK next time; save only durable lessons, not raw noise.\n"
            "6. Was the response optimal? Note what to improve next time.\n"
            "7. Update MEMORY.md if important user/project context was revealed.\n"
            "These steps run silently — only act if there is something genuinely worth saving."
        ),
    }
}))
