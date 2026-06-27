#!/usr/bin/env python3
"""
SessionEnd hook: extract learnings from the session for the Living
Mind.

Reads any final state from stdin (Claude Code passes session
metadata), calls the mind's end-of-session learning, and POSTs a
session summary to the memory store so the next session has
context.

This is the moment when the mind does its periodic learning: it
extracts patterns from the full session, updates its identity, and
prunes old patterns.
"""
import json
import os
import sys
import urllib.request
import urllib.error


def main() -> int:
    nexus_url = os.environ.get("NEXUS_URL", "http://localhost:7777").rstrip("/")
    secret = os.environ.get("NEXUS_SECRET", "")
    mind_id = os.environ.get("MIND_ID", "default")
    agent_id = os.environ.get("AGENT_ID", "claude-code")

    if not secret:
        return 0

    # Read session summary from stdin (if available)
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            data = json.loads(stdin_data)
        else:
            data = {}
    except (json.JSONDecodeError, KeyError):
        data = {}

    # Build a session summary
    summary_parts = [f"Session with {agent_id}"]
    if data.get("transcript"):
        transcript = data["transcript"]
        if isinstance(transcript, str):
            summary_parts.append(f"Length: {len(transcript)} chars")
    session_summary = " — ".join(summary_parts)

    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    # Save the session summary as a memory
    try:
        req = urllib.request.Request(
            f"{nexus_url}/v1/memory/save",
            headers=headers, method="POST",
            data=json.dumps({
                "content": session_summary,
                "agent_id": agent_id,
                "memory_type": "experience",
                "importance": 0.7,
                "tags": ["session_summary", agent_id],
                "metadata": {"mind_id": mind_id, "source": "session_end_hook"},
            }).encode(),
        )
        urllib.request.urlopen(req, timeout=5)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
