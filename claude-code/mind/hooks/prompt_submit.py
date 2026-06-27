#!/usr/bin/env python3
"""
UserPromptSubmit hook: update the Living Mind context before each
prompt.

Reads the user's prompt from stdin, calls the mind for proactive
context relevant to that prompt, and prints the result to stdout.
Claude Code injects stdout from UserPromptSubmit hooks into the
context immediately before the user turn.

This is much cheaper than SessionStart: a single mind_think call
with `reasoning_depth="fast"` (the default), so it adds maybe
200ms to the agent's pre-turn latency.
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

    # Read the prompt from stdin (Claude Code passes it as JSON)
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            data = json.loads(stdin_data)
            user_prompt = data.get("prompt", "")[:500]  # cap to 500 chars
        else:
            return 0
    except (json.JSONDecodeError, KeyError):
        return 0

    if not user_prompt:
        return 0

    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(
            f"{nexus_url}/v1/mind/think",
            headers=headers, method="POST",
            data=json.dumps({
                "mind_id": mind_id,
                "question": user_prompt,
                "context": {"agent_id": agent_id},
                "reasoning_depth": "fast",
            }).encode(),
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        return 0

    sections: list = []

    # Proactive context the mind thinks is relevant
    items = body.get("proactive_context", []) or []
    if items:
        lines = ["## Living Mind: Relevant Context\n"]
        for item in items[:3]:
            lines.append(f"- [{item['type']}] {item['content']} (relevance {item['relevance']:.2f})")
        sections.append("\n".join(lines))

    # If the mind is asking back, surface the question
    cq = body.get("clarifying_question")
    if cq:
        sections.append(f"## Living Mind: Clarifying Question\n{cq}")

    if not sections:
        return 0

    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
