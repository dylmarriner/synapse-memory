#!/usr/bin/env python3
"""
PostToolUse hook: capture tool observations for the Living Mind.

Reads the tool event from stdin, builds a concise observation,
and POSTs it to the mind for processing.  The mind forms opinions,
updates identity, and logs the learning event.

This is fire-and-forget — a 1-second timeout, no waiting for
response, no failure on error.  The agent never blocks on memory.
"""
import json
import os
import sys
import urllib.request
import urllib.error


_INTERESTING_TOOLS = {
    "Write", "Edit", "MultiEdit", "Bash", "Read", "Grep", "Glob",
    "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite",
}


def main() -> int:
    nexus_url = os.environ.get("NEXUS_URL", "http://localhost:7777").rstrip("/")
    secret = os.environ.get("NEXUS_SECRET", "")
    mind_id = os.environ.get("MIND_ID", "default")
    agent_id = os.environ.get("AGENT_ID", "claude-code")

    if not secret:
        return 0

    try:
        stdin_data = sys.stdin.read()
        if not stdin_data.strip():
            return 0
        data = json.loads(stdin_data)
    except (json.JSONDecodeError, KeyError):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in _INTERESTING_TOOLS:
        return 0

    # Build a concise observation
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    tool_output = data.get("tool_output", "")
    if not isinstance(tool_output, str):
        tool_output = str(tool_output)[:200]

    # Summarise the input as a short observation
    input_str = json.dumps(tool_input)[:300] if tool_input else ""
    observation = f"Used {tool_name}"
    if input_str:
        observation += f": {input_str}"
    if tool_output:
        observation += f"\nResult: {tool_output[:200]}"

    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    try:
        # Use the standard memory_save endpoint — the mind's
        # MemoryRouter on the server side will route it through
        # the mind for processing.
        payload = {
            "content": observation,
            "agent_id": agent_id,
            "memory_type": "experience",
            "importance": 0.4,
            "tags": ["tool_use", tool_name.lower(), "auto_capture"],
            "metadata": {"mind_id": mind_id, "source": "post_tool_use_hook"},
        }
        req = urllib.request.Request(
            f"{nexus_url}/v1/memory/save",
            headers=headers, method="POST",
            data=json.dumps(payload).encode(),
        )
        urllib.request.urlopen(req, timeout=3)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        # Fire and forget — never fail the agent because of a hook
        pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
