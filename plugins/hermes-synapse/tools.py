"""Synapse Memory — Hermes plugin: tool handlers.

These handlers forward tool calls to the Synapse MCP server.
"""

import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SYNAPSE_SERVER_URL = os.environ.get(
    "SYNAPSE_SERVER_URL", "http://100.91.55.113:8765/mcp"
)
SYNAPSE_API_KEY = os.environ.get("SYNAPSE_API_KEY", "")
DEFAULT_PROJECT = os.environ.get("SYNAPSE_PROJECT", "default")

_session_id = None
_session_expiry = 0


def _call_server(tool: str, args: dict) -> dict:
    """Make a raw MCP tool call to the Synapse server."""
    global _session_id, _session_expiry

    now = time.time()
    if not _session_id or now > _session_expiry:
        # Initialize session
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "hermes-plugin", "version": "1.0"},
            },
        }).encode("utf-8")

        req = Request(
            SYNAPSE_SERVER_URL, data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            _session_id = resp.headers.get("mcp-session-id", "")
            _session_expiry = now + 840  # 14 min

    # Build args with auth
    call_args = dict(args)
    if SYNAPSE_API_KEY:
        call_args["api_key"] = SYNAPSE_API_KEY

    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": call_args},
    }).encode("utf-8")

    req = Request(
        SYNAPSE_SERVER_URL, data=body,
        headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Mcp-Session-Id": _session_id,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}"}

    if "error" in data:
        return {"error": data["error"].get("message", str(data["error"]))}

    result = data.get("result", {})
    content = result.get("content", [])
    if content:
        try:
            return json.loads(content[0]["text"])
        except (json.JSONDecodeError, KeyError):
            return {"error": "Failed to parse server response"}
    return result.get("structuredContent", {})


def synapse_health(args: dict, **kwargs) -> str:
    """Check server status."""
    try:
        result = _call_server("health", {})
        if result.get("ok"):
            return json.dumps({
                "status": "operational",
                "tailscale_ip": result.get("tailscale_ip"),
                "hostname": result.get("hostname"),
                "memories": result.get("memories", 0),
                "tenants": result.get("tenants", 0),
                "version": result.get("version", "?"),
            })
        return json.dumps({"status": "degraded", "error": result.get("error", "unknown")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_store(args: dict, **kwargs) -> str:
    """Store a memory."""
    try:
        content = args.get("content", "").strip()
        if not content:
            return json.dumps({"error": "No content provided"})
        result = _call_server("store", {
            "project_key": args.get("project_key", DEFAULT_PROJECT),
            "kind": args.get("kind", "semantic"),
            "content": content,
            "tags": args.get("tags", []),
            "importance": args.get("importance", 0.5),
            "source": "hermes",
        })
        if result.get("ok"):
            return json.dumps({
                "memory_id": result["memory_id"],
                "version": result.get("version", 1),
                "message": f"Memory stored (v{result.get('version', 1)})",
            })
        return json.dumps({"error": result.get("error", "Store failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_retrieve(args: dict, **kwargs) -> str:
    """Search memories."""
    try:
        query = args.get("query", "")
        if not query:
            return json.dumps({"error": "No query provided"})
        result = _call_server("retrieve", {
            "query": query,
            "project_key": args.get("project_key", DEFAULT_PROJECT),
            "kinds": args.get("kinds"),
            "limit": args.get("limit", 10),
        })
        if result.get("ok"):
            items = result.get("results", [])
            return json.dumps({
                "count": len(items),
                "results": [
                    {
                        "score": m.get("score", 0),
                        "content": m.get("content_text", "")[:200],
                        "kind": m.get("kind"),
                        "tags": m.get("tags", []),
                        "memory_id": m.get("memory_id", ""),
                    }
                    for m in items[:20]
                ],
            })
        return json.dumps({"error": result.get("error", "Retrieve failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_update(args: dict, **kwargs) -> str:
    """Update a memory."""
    try:
        memory_id = args.get("memory_id", "")
        content = args.get("content", "")
        if not memory_id or not content:
            return json.dumps({"error": "memory_id and content required"})
        result = _call_server("update", {
            "memory_id": memory_id,
            "content": content,
            "merge_strategy": args.get("merge_strategy", "merge"),
        })
        if result.get("ok"):
            return json.dumps({
                "memory_id": memory_id,
                "version": result.get("version", "?"),
                "message": f"Updated to v{result.get('version', '?')}",
            })
        return json.dumps({"error": result.get("error", "Update failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_delete(args: dict, **kwargs) -> str:
    """Delete a memory."""
    try:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return json.dumps({"error": "memory_id required"})
        result = _call_server("delete", {
            "memory_id": memory_id,
            "reason": args.get("reason", ""),
        })
        if result.get("ok"):
            return json.dumps({"status": "deleted", "memory_id": memory_id})
        return json.dumps({"error": result.get("error", "Delete failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_context(args: dict, **kwargs) -> str:
    """Get optimized context pack."""
    try:
        result = _call_server("context", {
            "query": args.get("query", ""),
            "project_key": args.get("project_key", DEFAULT_PROJECT),
            "limit": args.get("limit", 5),
        })
        if result.get("ok"):
            memories = result.get("memories", [])
            return json.dumps({
                "tokens_saved": result.get("tokens_saved", 0),
                "compression_ratio": result.get("compression_ratio", 0),
                "count": len(memories),
                "results": [
                    {
                        "score": m.get("score", 0),
                        "content": m.get("content_text", "")[:300],
                        "kind": m.get("kind"),
                    }
                    for m in memories[:10]
                ],
            })
        return json.dumps({"error": result.get("error", "Context failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})


def synapse_rank(args: dict, **kwargs) -> str:
    """Rank memories by importance."""
    try:
        result = _call_server("rank", {
            "project_key": args.get("project_key", DEFAULT_PROJECT),
            "limit": args.get("limit", 20),
        })
        if result.get("ok"):
            ranked = result.get("ranked", [])
            return json.dumps({
                "count": len(ranked),
                "ranked": [
                    {
                        "score": r.get("importance_score", 0),
                        "action": r.get("suggested_action"),
                        "kind": r.get("kind"),
                        "memory_id": r.get("memory_id", ""),
                    }
                    for r in ranked[:20]
                ],
            })
        return json.dumps({"error": result.get("error", "Rank failed")})
    except Exception as e:
        return json.dumps({"error": str(e)})
