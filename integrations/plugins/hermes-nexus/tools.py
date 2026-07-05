"""Nexus Memory — Hermes plugin: tool handlers.

Forwards tool calls to the Nexus MCP server via Bearer token auth.

Env vars:
  NEXUS_URL     — MCP endpoint (default: http://100.93.75.87:7777/mcp)
  NEXUS_SECRET  — Bearer token
  NEXUS_AGENT   — Agent ID for this Hermes instance (default: hermes)
"""

import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

NEXUS_URL = os.environ.get("NEXUS_URL", "http://100.93.75.87:7777/mcp")
NEXUS_SECRET = os.environ.get("NEXUS_SECRET", "")
NEXUS_AGENT = os.environ.get("NEXUS_AGENT", "hermes")


def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if NEXUS_SECRET:
        h["Authorization"] = f"Bearer {NEXUS_SECRET}"
    return h


def _call(tool: str, args: dict) -> dict:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }).encode()
    req = Request(NEXUS_URL, data=body, headers=_headers(), method="POST")
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}"}
    if "error" in data:
        return {"error": data["error"].get("message", str(data["error"]))}
    content = data.get("result", {}).get("content", [])
    if content:
        try:
            return json.loads(content[0]["text"])
        except (json.JSONDecodeError, KeyError):
            return {"raw": content[0].get("text", "")}
    return data.get("result", {})


# ── Tool handlers ─────────────────────────────────────────────────────────────

def nexus_health(args: dict, **_) -> str:
    result = _call("nexus_status", {})
    return json.dumps(result)


def nexus_store(args: dict, **_) -> str:
    content = args.get("content", "").strip()
    if not content:
        return json.dumps({"error": "content required"})
    result = _call("memory_save", {
        "content": content,
        "agent_id": args.get("agent_id", NEXUS_AGENT),
        "memory_type": args.get("kind") or args.get("memory_type"),
        "importance": args.get("importance", 0.5),
        "tags": args.get("tags", []),
    })
    return json.dumps(result)


def nexus_recall(args: dict, **_) -> str:
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query required"})
    result = _call("memory_recall", {
        "query": query,
        "agent_id": args.get("agent_id", NEXUS_AGENT),
        "limit": args.get("limit", 10),
        "memory_types": args.get("kinds", []),
    })
    return json.dumps(result)


def nexus_context(args: dict, **_) -> str:
    result = _call("agent_context", {
        "agent_id": args.get("agent_id", NEXUS_AGENT),
        "tokens": args.get("tokens", 2000),
    })
    return json.dumps(result)


def nexus_learn(args: dict, **_) -> str:
    agent_id = args.get("agent_id", NEXUS_AGENT)
    content = args.get("content", "").strip()
    if not content:
        return json.dumps({"error": "content required"})
    result = _call("agent_learn", {
        "agent_id": agent_id,
        "content": content,
        "importance": args.get("importance", 0.5),
        "tags": args.get("tags", []),
    })
    return json.dumps(result)


def nexus_reflect(args: dict, **_) -> str:
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query required"})
    result = _call("memory_reflect", {
        "query": query,
        "agent_id": args.get("agent_id", NEXUS_AGENT),
        "depth": args.get("depth", "mid"),
    })
    return json.dumps(result)
