#!/usr/bin/env python3
"""
SessionStart hook: build a Living Mind briefing and inject it into
the agent's system prompt.

This runs once at the start of every Claude Code session.  It asks
the running Nexus server for the mind's identity + proactive context
+ relationship, then prints the result to stdout — Claude Code
injects anything printed by SessionStart hooks into the system
prompt before the first user turn.

Required env:
    NEXUS_URL     - base URL of the Nexus server, default http://localhost:7777
    NEXUS_SECRET  - bearer token
    MIND_ID      - which mind to query, default "default"
    AGENT_ID     - which agent is starting, default "claude-code"
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
        # Without auth we can't reach the mind; fail silent so the
        # session starts even if Nexus is unreachable.
        return 0

    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    sections: list = []

    # 1. Mind identity — "I am a living mind, here's who I am"
    try:
        req = urllib.request.Request(
            f"{nexus_url}/v1/mind/identity/{mind_id}",
            headers=headers, method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            if body.get("description"):
                sections.append(body["description"])
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        pass

    # 2. Proactive context — what the mind thinks you should know
    try:
        req = urllib.request.Request(
            f"{nexus_url}/v1/mind/think",
            headers=headers, method="POST",
            data=json.dumps({
                "mind_id": mind_id,
                "question": "What should I know right now?",
                "context": {"agent_id": agent_id, "proactive_only": True},
            }).encode(),
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            items = body.get("proactive_context", []) or []
            if items:
                lines = ["## Proactive Context (from the Living Mind)\n"]
                for item in items[:5]:
                    lines.append(f"- [{item['type']}] {item['content']} (relevance {item['relevance']:.2f})")
                sections.append("\n".join(lines))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        pass

    # 3. The mind's opinions on the current agent's projects
    try:
        req = urllib.request.Request(
            f"{nexus_url}/v1/mind/opinions/{mind_id}",
            headers=headers, method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            opinions = body.get("opinions", {}) or {}
            if isinstance(opinions, dict) and opinions:
                lines = ["## Mind's Opinions\n"]
                for topic, op in list(opinions.items())[:3]:
                    if op is None:
                        continue
                    lines.append(
                        f"- **{topic}**: {op['stance']} (strength {op['strength']:.2f}, "
                        f"{op['evidence_count']} pieces of evidence)"
                    )
                sections.append("\n".join(lines))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        pass

    if not sections:
        return 0

    # Print to stdout — Claude Code injects this into the system prompt
    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never fail a session start because of a mind hook error
        sys.exit(0)
