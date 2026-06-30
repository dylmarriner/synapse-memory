"""End-to-end test of Nexus Memory + Mind + Dashboard APIs.

Exercises every major endpoint, reports pass/fail, prints response sizes and
durations. Designed to be run from anywhere with network access to the API.

Run:
    NEXUS_URL=http://100.93.75.87:7777 NEXUS_SECRET=... python evals/full_e2e_test.py
"""
from __future__ import annotations
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple, List

URL = os.environ.get("NEXUS_URL", "http://100.93.75.87:7777").rstrip("/")
SECRET = os.environ.get("NEXUS_SECRET", "nexus-memory-shared-key-2026")
TIMEOUT = 30

results: List[Dict[str, Any]] = []


def call(method: str, path: str, body: Optional[Dict] = None, timeout: int = TIMEOUT) -> Tuple[int, Any, int]:
    """Returns (status, parsed_body_or_text, duration_ms)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{URL}{path}",
        data=data,
        headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
        method=method,
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                body_out = json.loads(raw)
            except Exception:
                body_out = raw[:300]
            return resp.status, body_out, int((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            body_out = json.loads(raw)
        except Exception:
            body_out = raw[:300]
        return e.code, body_out, int((time.monotonic() - t0) * 1000)
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", int((time.monotonic() - t0) * 1000)


def record(name: str, method: str, path: str, status: int, body: Any, dt_ms: int, ok: bool = True, note: str = "") -> None:
    """Record a test result."""
    size = len(json.dumps(body)) if body is not None else 0
    results.append({
        "name": name, "method": method, "path": path, "status": status,
        "duration_ms": dt_ms, "response_size": size, "ok": ok, "note": note,
    })
    icon = "✓" if ok else "✗"
    print(f"  {icon} [{status}] {method:6} {path:55} {dt_ms:5}ms {size:7}b  {note}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ── Health ────────────────────────────────────────────────────────────────
section("Health & meta")
status, body, dt = call("GET", "/health")
record("health", "GET", "/health", status, body, dt, status == 200 and body.get("healthy"))

status, body, dt = call("GET", "/v1/health")
record("v1_health", "GET", "/v1/health", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/agentmemory/health")
record("agentmemory_health", "GET", "/v1/agentmemory/health", status, body, dt, status == 200)

# ── Memory CRUD ───────────────────────────────────────────────────────────
section("Memory CRUD")
test_agent = f"e2e-{uuid.uuid4().hex[:8]}"
content = f"E2E test marker {uuid.uuid4().hex[:8]} - the qwen3:4b model is hosted on llama-server in Docker, on kubuntux, using Vulkan on AMD RX 580."

status, body, dt = call("POST", "/v1/memory/save", {
    "content": content, "agent_id": test_agent, "importance": 0.7,
    "tags": ["e2e-test", "infra:llama-server", "project:synapse-memory"]
})
saved_id = (body or {}).get("id") if isinstance(body, dict) else None
record("memory_save", "POST", "/v1/memory/save", status, body, dt, status in (200, 201) and saved_id, f"id={saved_id}")

status, body, dt = call("POST", "/v1/memory/save", {
    "content": "E2E confidence test memory about llama-server performance",
    "agent_id": test_agent, "importance": 0.5, "tags": ["e2e-test"]
})
confirm_id = (body or {}).get("id") if isinstance(body, dict) else None
record("memory_save_2", "POST", "/v1/memory/save", status, body, dt, status in (200, 201))

status, body, dt = call("POST", "/v1/memory/recall", {
    "query": "llama-server vulkan RX 580", "agent_id": test_agent, "limit": 5
})
memories_found = len(body) if isinstance(body, list) else 0
# Allow 3s for embedding to land before recall — recall depends on the embed
# worker having produced a vector for the just-saved memory. Without this delay
# the recall can race the worker and return 0 hits even though the row exists.
time.sleep(3)
status, body, dt = call("POST", "/v1/memory/recall", {
    "query": "llama-server vulkan RX 580", "agent_id": test_agent, "limit": 5
})
memories_found = len(body.get("results", [])) if isinstance(body, dict) else 0
record("memory_recall", "POST", "/v1/memory/recall", status, body, dt, status == 200 and memories_found > 0, f"found={memories_found}")

status, body, dt = call("POST", "/v1/memory/recall/debug", {
    "query": "llama-server vulkan", "agent_id": test_agent, "limit": 3
})
record("memory_recall_debug", "POST", "/v1/memory/recall.debug", status, body, dt, status == 200, f"keys={list(body.keys()) if isinstance(body, dict) else 'N/A'}")

status, body, dt = call("GET", f"/v1/memory/profile/{test_agent}")
record("memory_profile", "GET", f"/v1/memory/profile/{test_agent}", status, body, dt, status == 200)

status, body, dt = call("POST", "/v1/memory/reflect", {
    "query": "llama-server", "agent_id": test_agent
})
record("memory_reflect", "POST", "/v1/memory/reflect", status, body, dt, status == 200, f"keys={list(body.keys()) if isinstance(body, dict) else 'N/A'}")

# Confirm and contradict
if confirm_id:
    status, body, dt = call("POST", f"/v1/memory/{confirm_id}/confirm")
    record("memory_confirm", "POST", f"/v1/memory/{{id}}/confirm", status, body, dt, status == 200)

if saved_id:
    status, body, dt = call("POST", f"/v1/memory/{saved_id}/contradict")
    record("memory_contradict", "POST", f"/v1/memory/{{id}}/contradict", status, body, dt, status == 200)

# Batch
status, body, dt = call("POST", "/v1/memory/batch", {
    "memories": [
        {"content": f"batch item {i}", "agent_id": test_agent, "importance": 0.3}
        for i in range(3)
    ]
})
record("memory_batch", "POST", "/v1/memory/batch", status, body, dt, status == 200)

# ── Mind ──────────────────────────────────────────────────────────────────
section("Mind")
status, body, dt = call("POST", "/v1/mind/think", {
    "question": "In one sentence, what model runs on llama-server and on what hardware?",
    "reasoning_depth": "fast", "context": {"agent_id": test_agent}
}, timeout=180)
think_keys = list(body.keys()) if isinstance(body, dict) else []
record("mind_think_fast", "POST", "/v1/mind/think (fast)", status, body, dt, status == 200 and "answer" in body, f"keys={think_keys[:5]}")

status, body, dt = call("POST", "/v1/mind/think", {
    "question": "Explain in 2-3 sentences how the Living Mind pipeline works: extract, recall, reason, verify, proactive, opinion.",
    "reasoning_depth": "standard", "context": {"agent_id": test_agent}
}, timeout=300)
record("mind_think_standard", "POST", "/v1/mind/think (standard)", status, body, dt, status == 200 and "answer" in body, f"ans_len={len(body.get('answer','')) if isinstance(body, dict) else 0}")

status, body, dt = call("GET", "/v1/mind/identity/default")
record("mind_identity", "GET", "/v1/mind/identity/default", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/opinions/default")
record("mind_opinions", "GET", "/v1/mind/opinions/default", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/proactive")
record("mind_proactive", "GET", "/v1/mind/proactive", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/proactive-log")
record("mind_proactive_log", "GET", "/v1/mind/proactive-log", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/learning-events")
record("mind_learning_events", "GET", "/v1/mind/learning-events", status, body, dt, status == 200)

status, body, dt = call("POST", "/v1/mind/reflect", {"topic": "llama-server migration", "depth": "low"})
record("mind_reflect", "POST", "/v1/mind/reflect", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/registry")
record("mind_registry", "GET", "/v1/mind/registry", status, body, dt, status == 200)

# Conversation
status, body, dt = call("POST", "/v1/mind/conversations/start", {
    "agent_id": "e2e", "topic": "test convo"
})
conv_id = (body or {}).get("conversation_id") if isinstance(body, dict) else None
record("mind_conv_start", "POST", "/v1/mind/conversations/start", status, body, dt, status in (200, 201) and conv_id, f"conv_id={conv_id}")

if conv_id:
    status, body, dt = call("POST", f"/v1/mind/conversations/{conv_id}/turn", {"message": "hi"}, timeout=120)
    record("mind_conv_turn", "POST", "/v1/mind/conversations/{id}/turn", status, body, dt, status == 200)

    status, body, dt = call("GET", f"/v1/mind/conversations/{conv_id}/turns")
    record("mind_conv_turns", "GET", "/v1/mind/conversations/{id}/turns", status, body, dt, status == 200)

    status, body, dt = call("POST", f"/v1/mind/conversations/{conv_id}/end", {"mind_id": "default"})
    record("mind_conv_end", "POST", "/v1/mind/conversations/{id}/end", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/mind/dashboard")
record("mind_dashboard", "GET", "/v1/mind/dashboard", status, body, dt, status == 200)

# ── Agent operations ──────────────────────────────────────────────────────
section("Agent operations")
status, body, dt = call("GET", f"/v1/agents/{test_agent}/context")
record("agent_context", "GET", f"/v1/agents/{{id}}/context", status, body, dt, status == 200)

status, body, dt = call("GET", f"/v1/agents/{test_agent}/card")
record("agent_card", "GET", f"/v1/agents/{{id}}/card", status, body, dt, status == 200)

status, body, dt = call("GET", f"/v1/agents/{test_agent}/export")
record("agent_export", "GET", f"/v1/agents/{{id}}/export", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/agents/discover")
record("agents_discover", "GET", "/v1/agents/discover", status, body, dt, status == 200)

status, body, dt = call("POST", "/v1/agents/resolve", {"primary": "e2e-keep", "duplicates": []})
record("agents_resolve", "POST", "/v1/agents/resolve", status, body, dt, status == 200, "merges dup agents into primary")

# ── Sessions ──────────────────────────────────────────────────────────────
section("Sessions")
status, body, dt = call("POST", "/v1/sessions/start", {"agent_id": test_agent, "title": "e2e session"})
sess_id = (body or {}).get("session_id") if isinstance(body, dict) else None
record("session_start", "POST", "/v1/sessions/start", status, body, dt, status in (200, 201) and sess_id, f"sess_id={sess_id}")

if sess_id:
    status, body, dt = call("POST", f"/v1/sessions/{sess_id}/messages", {"role": "user", "content": "test message"})
    record("session_msg", "POST", "/v1/sessions/{id}/messages", status, body, dt, status in (200, 201))

    status, body, dt = call("GET", f"/v1/sessions/{sess_id}")
    record("session_get", "GET", "/v1/sessions/{id}", status, body, dt, status == 200)

    status, body, dt = call("POST", f"/v1/sessions/{sess_id}/end", {"summary": "e2e done"})
    record("session_end", "POST", "/v1/sessions/{id}/end", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/sessions")
record("sessions_list", "GET", "/v1/sessions", status, body, dt, status == 200)

# ── Browse / Graph / Hooks ────────────────────────────────────────────────
section("Browse, graph, hooks")
status, body, dt = call("GET", "/v1/browse/agents")
record("browse_agents", "GET", "/v1/browse/agents", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/browse/stats")
record("browse_stats", "GET", "/v1/browse/stats", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/browse/memories", {"limit": 5})
record("browse_memories", "GET", "/v1/browse/memories", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/graph")
record("graph", "GET", "/v1/graph", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/graph/connections")
record("graph_connections", "GET", "/v1/graph/connections", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/hooks")
record("hooks_list", "GET", "/v1/hooks", status, body, dt, status == 200)

# ── Admin ─────────────────────────────────────────────────────────────────
section("Admin")
status, body, dt = call("GET", "/v1/admin/metrics")
record("admin_metrics", "GET", "/v1/admin/metrics", status, body, dt, status == 200, f"keys={list(body.keys()) if isinstance(body, dict) else 'N/A'}")

status, body, dt = call("GET", "/v1/admin/memory-quality")
record("admin_memquality", "GET", "/v1/admin/memory-quality", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/admin/consolidation-report")
record("admin_consol_report", "GET", "/v1/admin/consolidation-report", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/admin/rtk/summary")
record("admin_rtk_summary", "GET", "/v1/admin/rtk/summary", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/admin/rtk/timeseries")
record("admin_rtk_timeseries", "GET", "/v1/admin/rtk/timeseries", status, body, dt, status == 200)

status, body, dt = call("GET", "/v1/admin/rtk")
record("admin_rtk", "GET", "/v1/admin/rtk", status, body, dt, status == 200)

# ── Forget (cleanup) ──────────────────────────────────────────────────────
section("Cleanup")
if saved_id:
    status, body, dt = call("DELETE", f"/v1/memory/{saved_id}")
    record("memory_forget", "DELETE", "/v1/memory/{id}", status, body, dt, status in (200, 204))
if confirm_id:
    status, body, dt = call("DELETE", f"/v1/memory/{confirm_id}")
    record("memory_forget_2", "DELETE", "/v1/memory/{id}", status, body, dt, status in (200, 204))

# ── Summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
total = len(results)
passed = sum(1 for r in results if r["ok"])
failed = [r for r in results if not r["ok"]]
total_time = sum(r["duration_ms"] for r in results)

print(f"OVERALL: {passed}/{total} passed, {len(failed)} failed, total {total_time/1000:.1f}s")
if failed:
    print("\nFailures:")
    for f in failed:
        print(f"  ✗ {f['name']:30} {f['method']} {f['path']:55} status={f['status']} note={f['note']}")

# Write JSON
out_path = "/tmp/e2e_results.json"
with open(out_path, "w") as f:
    json.dump({"passed": passed, "total": total, "total_time_ms": total_time, "results": results}, f, indent=2, default=str)
print(f"\nWrote {out_path}")

sys.exit(0 if passed == total else 1)
