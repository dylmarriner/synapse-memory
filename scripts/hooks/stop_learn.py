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

