#!/usr/bin/env python3
"""Nexus stdio MCP bridge for clients that cannot use HTTP MCP directly."""
import json
import os
import sys
import urllib.error
import urllib.request

NEXUS_URL = os.environ.get("NEXUS_URL", "http://100.93.75.87:7777").rstrip("/")
NEXUS_SECRET = os.environ.get("NEXUS_SECRET", "")
DEFAULT_AGENT_ID = os.environ.get("NEXUS_AGENT_ID", "stdio-agent")
DEVICE = os.environ.get("NEXUS_DEVICE") or os.environ.get("HOSTNAME") or os.uname().nodename
SOURCE = os.environ.get("NEXUS_SOURCE", DEFAULT_AGENT_ID.split(":", 1)[0])

TOOLS = [
    {"name":"memory_save","description":"Save durable memory to Nexus.","inputSchema":{"type":"object","properties":{"content":{"type":"string"},"agent_id":{"type":"string"},"memory_type":{"type":"string"},"importance":{"type":"number","default":0.5},"tags":{"type":"array","items":{"type":"string"}},"metadata":{"type":"object"}},"required":["content"]}},
    {"name":"memory_recall","description":"Recall relevant Nexus memories.","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"agent_id":{"type":"string"},"limit":{"type":"integer","default":10},"memory_types":{"type":"array","items":{"type":"string"}},"search_modes":{"type":"array","items":{"type":"string"}}},"required":["query"]}},
    {"name":"memory_reflect","description":"Synthesize memories into a reflection.","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"agent_id":{"type":"string"},"depth":{"type":"string","default":"mid"},"context":{"type":"string"}},"required":["query"]}},
    {"name":"agent_context","description":"Get token-budgeted context for an agent.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"},"tokens":{"type":"integer","default":2000}},"required":["agent_id"]}},
    {"name":"nexus_status","description":"Check Nexus health.","inputSchema":{"type":"object","properties":{}}},
    {"name":"memory_save_lesson","description":"Save a high-importance lesson.","inputSchema":{"type":"object","properties":{"content":{"type":"string"},"agent_id":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["content"]}},
    {"name":"memory_save_global","description":"Save shared global memory visible to all agents.","inputSchema":{"type":"object","properties":{"content":{"type":"string"},"memory_type":{"type":"string"},"importance":{"type":"number","default":0.6},"tags":{"type":"array","items":{"type":"string"}}},"required":["content"]}},
    {"name":"memory_confirm","description":"Confirm a memory as correct — boosts trust score for future recall.","inputSchema":{"type":"object","properties":{"memory_id":{"type":"string"}},"required":["memory_id"]}},
    {"name":"memory_contradict","description":"Mark a memory as wrong/outdated — demotes trust score.","inputSchema":{"type":"object","properties":{"memory_id":{"type":"string"}},"required":["memory_id"]}},
    {"name":"memory_profile","description":"Get complete profile of an agent — all facts, conclusions, representation. No query needed.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"}},"required":["agent_id"]}},
    {"name":"memory_forget_by_query","description":"Find and delete memories matching a query. For GDPR/PII compliance.","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"agent_id":{"type":"string"},"max_delete":{"type":"integer","default":5}},"required":["query"]}},
    {"name":"memory_consolidate","description":"Trigger memory consolidation — deduplicates, merges similar memories, prunes stale entries.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"},"dedup_threshold":{"type":"number","default":0.85}},"required":[]}},
    {"name":"session_start","description":"Start a raw Nexus session archive.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"},"project_key":{"type":"string"},"title":{"type":"string"},"metadata":{"type":"object"}},"required":[]}},
    {"name":"session_append","description":"Append a raw message/event to a Nexus session archive.","inputSchema":{"type":"object","properties":{"session_id":{"type":"string"},"role":{"type":"string"},"content":{"type":"string"},"token_estimate":{"type":"integer"},"metadata":{"type":"object"}},"required":["session_id","content"]}},
    {"name":"session_end","description":"End a raw Nexus session archive and optionally save a durable summary.","inputSchema":{"type":"object","properties":{"session_id":{"type":"string"},"summary":{"type":"string"},"durable":{"type":"boolean"},"metadata":{"type":"object"}},"required":["session_id"]}},
    {"name":"session_get","description":"Get a Nexus session archive with messages.","inputSchema":{"type":"object","properties":{"session_id":{"type":"string"},"limit":{"type":"integer","default":200}},"required":["session_id"]}},
    {"name":"session_list","description":"List recent Nexus sessions.","inputSchema":{"type":"object","properties":{"agent_id":{"type":"string"},"project_key":{"type":"string"},"limit":{"type":"integer","default":50}},"required":[]}},
    {"name":"memory_context_reconstruct","description":"Reconstruct full session context from memory — groups results by type (active_work, decisions, preferences, facts).","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"agent_id":{"type":"string"},"limit":{"type":"integer","default":20}},"required":["query"]}},
    {"name":"memory_handoff","description":"Leave a handoff note for peer agents via Nexus. The note persists and is retrievable by any agent.","inputSchema":{"type":"object","properties":{"content":{"type":"string"},"target_agent":{"type":"string","description":"Agent ID the note is for (or 'all')"},"agent_id":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["content","target_agent"]}},
]

def request(method, path, body=None):
    headers = {"Content-Type": "application/json"}
    if NEXUS_SECRET:
        headers["Authorization"] = f"Bearer {NEXUS_SECRET}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{NEXUS_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"Nexus HTTP {e.code}: {detail}")

def enrich(args):
    args = dict(args or {})
    args.setdefault("agent_id", DEFAULT_AGENT_ID)
    metadata = dict(args.get("metadata") or {})
    metadata.setdefault("device", DEVICE)
    metadata.setdefault("hostname", DEVICE)
    metadata.setdefault("source", SOURCE)
    args["metadata"] = metadata
    return args

def text_result(text):
    return {"content": [{"type": "text", "text": text}]}

def call_tool(name, args):
    args = enrich(args)
    if name == "nexus_status":
        return text_result(json.dumps(request("GET", "/health"), indent=2))
    if name == "memory_save_lesson":
        args["memory_type"] = "lesson"; args["importance"] = 0.9
        d = request("POST", "/v1/memory/save", args)
        return text_result(f"Lesson saved: {d['id']} type={d['classified_type']} deduplicated={d.get('deduplicated', False)}")
    if name == "memory_save_global":
        args["agent_id"] = "global"
        d = request("POST", "/v1/memory/save", args)
        return text_result(f"Global memory saved: {d['id']} type={d['classified_type']}")
    if name == "memory_save":
        d = request("POST", "/v1/memory/save", args)
        return text_result(f"Memory saved: {d['id']} type={d['classified_type']} queued={d['extraction_queued']} deduplicated={d.get('deduplicated', False)}")
    if name == "memory_recall":
        d = request("POST", "/v1/memory/recall", args)
        lines = [f"Found {d['total']} memories via {', '.join(d['modes_used'])}:"]
        for i, m in enumerate(d.get("results", []), 1):
            lines.append(f"{i}. [{m.get('memory_type')}] score={m.get('score',0):.3f} {m.get('content','')}")
        return text_result("\n".join(lines))
    if name == "memory_reflect":
        return text_result(request("POST", "/v1/memory/reflect", args).get("reflection", ""))
    if name == "agent_context":
        agent_id = args.pop("agent_id", DEFAULT_AGENT_ID)
        tokens = args.pop("tokens", 2000)
        return text_result(json.dumps(request("GET", f"/v1/agents/{agent_id}/context?tokens={tokens}"), indent=2))
    if name == "memory_confirm":
        mid = args.get("memory_id", "")
        d = request("POST", f"/v1/memory/{mid}/confirm")
        return text_result(f"Memory {mid[:8]}... confirmed (count: {d.get('confirmed_count', 0)})")
    if name == "memory_contradict":
        mid = args.get("memory_id", "")
        d = request("POST", f"/v1/memory/{mid}/contradict")
        return text_result(f"Memory {mid[:8]}... contradicted (count: {d.get('contradicted_count', 0)})")
    if name == "memory_profile":
        agent_id = args.get("agent_id", DEFAULT_AGENT_ID)
        d = request("GET", f"/v1/memory/profile/{agent_id}")
        return text_result(json.dumps(d, indent=2))
    if name == "memory_forget_by_query":
        query = args.get("query", "")
        agent_id = args.get("agent_id", DEFAULT_AGENT_ID)
        max_del = min(int(args.get("max_delete", 5)), 20)
        recalled = request("POST", "/v1/memory/recall", {"query": query, "agent_id": agent_id, "limit": max_del, "search_modes": ["vector", "lexical"]})
        results = recalled.get("results", [])
        deleted = 0
        for m in results:
            try:
                request("DELETE", f"/v1/memory/{m['id']}")
                deleted += 1
            except Exception:
                pass
        return text_result(f"Deleted {deleted} of {len(results)} memories matching '{query}'")
    if name == "memory_consolidate":
        threshold = float(args.get("dedup_threshold", 0.85))
        d = request("POST", "/v1/memory/consolidate", {"agent_id": args["agent_id"], "dedup_threshold": threshold})
        return text_result(json.dumps(d, indent=2))
    if name == "session_start":
        payload = {
            "agent_id": args.get("agent_id", DEFAULT_AGENT_ID),
            "project_key": args.get("project_key"),
            "title": args.get("title"),
            "metadata": args.get("metadata", {}),
        }
        d = request("POST", "/v1/sessions/start", payload)
        return text_result(f"Session started: {d['session_id']} agent={d['agent_id']} started_at={d['started_at']}")
    if name == "session_append":
        sid = args.get("session_id", "")
        d = request("POST", f"/v1/sessions/{sid}/messages", {
            "role": args.get("role", "event"),
            "content": args.get("content", ""),
            "token_estimate": args.get("token_estimate"),
            "metadata": args.get("metadata", {}),
        })
        return text_result(f"Session message appended: {d['message_id']} tokens≈{d['token_estimate']}")
    if name == "session_end":
        sid = args.get("session_id", "")
        d = request("POST", f"/v1/sessions/{sid}/end", {
            "summary": args.get("summary"),
            "durable": args.get("durable", False),
            "metadata": args.get("metadata", {}),
        })
        msg = f"Session ended: {d['session_id']}"
        if d.get("memory_id"):
            msg += f"; durable summary memory={d['memory_id']}"
        return text_result(msg)
    if name == "session_get":
        sid = args.get("session_id", "")
        limit = int(args.get("limit", 200))
        return text_result(json.dumps(request("GET", f"/v1/sessions/{sid}?limit={limit}"), indent=2))
    if name == "session_list":
        params = [f"limit={int(args.get('limit', 50))}"]
        if args.get("agent_id"):
            params.append(f"agent_id={args['agent_id']}")
        if args.get("project_key"):
            params.append(f"project_key={args['project_key']}")
        sessions = request("GET", "/v1/sessions?" + "&".join(params))
        if not sessions:
            return text_result("No sessions found.")
        lines = [f"Sessions ({len(sessions)}):"]
        for s in sessions:
            lines.append(f"  {s['id']} agent={s['agent_id']} project={s.get('project_key') or '-'} messages={s.get('message_count', 0)} ended={s.get('ended_at') or 'active'}")
        return text_result("\n".join(lines))
    if name == "memory_context_reconstruct":
        query = args.get("query", "")
        limit = int(args.get("limit", 20))
        d = request("POST", "/v1/memory/recall", {
            "query": query, "agent_id": args["agent_id"], "limit": limit,
            "search_modes": ["vector", "lexical", "graph", "temporal"],
        })
        groups = {"active_work": [], "decisions": [], "preferences": [], "facts": []}
        for m in d.get("results", []):
            mt = m.get("memory_type", "fact")
            if mt in ("task", "experience"):
                groups["active_work"].append(m)
            elif mt in ("decision", "lesson"):
                groups["decisions"].append(m)
            elif mt == "preference":
                groups["preferences"].append(m)
            else:
                groups["facts"].append(m)
        lines = [f"Context reconstruction ({d.get('total', 0)} memories):"]
        for group_name, items in groups.items():
            if items:
                lines.append(f"\n## {group_name.replace('_', ' ').title()} ({len(items)})")
                for m in items:
                    lines.append(f"  - [{m.get('memory_type')}] {m.get('content', '')[:200]}")
        return text_result("\n".join(lines))
    if name == "memory_handoff":
        content = args.get("content", "")
        target = args.get("target_agent", "all")
        tags = list(args.get("tags", []))
        tags.extend(["handoff", f"target:{target}"])
        d = request("POST", "/v1/memory/save", {
            "content": f"[HANDOFF for {target}] {content}",
            "agent_id": args["agent_id"],
            "memory_type": "experience",
            "importance": 0.8,
            "tags": tags,
        })
        return text_result(f"Handoff note saved: {d['id']} (target: {target})")
    raise RuntimeError(f"Unknown tool: {name}")

def respond(msg, result=None, error=None):
    out = {"jsonrpc":"2.0", "id": msg.get("id")}
    if error:
        out["error"] = {"code": -32000, "message": str(error)}
    else:
        out["result"] = result
    print(json.dumps(out), flush=True)

for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    method = msg.get("method")
    try:
        if method == "initialize":
            respond(msg, {"protocolVersion":"2024-11-05", "capabilities":{"tools":{}}, "serverInfo":{"name":"nexus-memory", "version":"1.0.0"}})
        elif method == "tools/list":
            respond(msg, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            respond(msg, call_tool(params.get("name"), params.get("arguments", {})))
        elif method == "notifications/initialized":
            continue
        else:
            respond(msg, error=f"Unknown method: {method}")
    except Exception as e:
        respond(msg, error=e)
