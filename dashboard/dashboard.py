#!/usr/bin/env python3
"""Synapse Dashboard — Web UI for Synapse Enterprise Memory.

Serves a beautiful futuristic dashboard at http://localhost:8767
that connects to the Synapse MCP server.

Usage:
  python3 dashboard.py                          # Default: connect to localhost:8765
  SYNAPSE_URL=http://100.68.0.96:8765/mcp ./dash.py  # Connect to rabuntu
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# ─── Config ─────────────────────────────────────────────────────────

SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://100.68.0.96:8765/mcp")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8767"))
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")

# ─── MCP Session ────────────────────────────────────────────────────

_session_id = None
_session_expiry = 0

def ensure_session():
    global _session_id, _session_expiry
    now = time.time()
    if _session_id and now < _session_expiry:
        return _session_id

    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "synapse-dashboard", "version": "0.1.0"},
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        SYNAPSE_URL, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        _session_id = resp.headers.get("mcp-session-id", "")
        _session_expiry = now + 840
    return _session_id

def mcp_call(tool: str, args: dict | None = None) -> dict:
    """Call an MCP tool on the Synapse server."""
    session_id = ensure_session()
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }).encode("utf-8")

    req = urllib.request.Request(
        SYNAPSE_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Mcp-Session-Id": session_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Connection failed: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if "error" in data:
        return {"ok": False, "error": data["error"].get("message", str(data["error"]))}

    result = data.get("result", {})
    content = result.get("content", [])
    if content:
        try:
            return json.loads(content[0]["text"])
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
    return result.get("structuredContent", {})


# ─── HTTP Handlers ──────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, data: dict, status: int = 200):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def _html(self, html: str):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _text(self, text: str):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self._html(DASHBOARD_HTML)
        elif path == "/api/health":
            result = mcp_call("health")
            self._json(result)
        elif path == "/api/status":
            h = mcp_call("health")
            self._json({
                "ok": h.get("ok", False),
                "server_url": SYNAPSE_URL,
                "tailscale_ip": h.get("tailscale_ip"),
                "hostname": h.get("hostname"),
                "memories": h.get("memories", 0),
                "tenants": h.get("tenants", 0),
                "version": h.get("version", "?"),
                "embedding_dim": h.get("embedding_dim", 0),
                "time": h.get("time"),
            })
        elif path.startswith("/api/search"):
            from urllib.parse import parse_qs
            qs = parse_qs(urlparse(self.path).query)
            query = qs.get("q", [""])[0]
            limit = int(qs.get("limit", ["20"])[0])
            project = qs.get("project", [""])[0]
            args = {"query": query, "limit": min(limit, 100)}
            if project:
                args["project_key"] = project
            result = mcp_call("retrieve", args)
            self._json(result)
        elif path == "/api/rank":
            result = mcp_call("rank", {"limit": 50})
            self._json(result)
        elif path == "/api/tenants":
            h = mcp_call("health")
            tenant_count = h.get("tenants", 0)
            self._json({"count": tenant_count})
        else:
            self._json({"error": "Not found", "path": path}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json({"error": "Invalid JSON"}, 400)
            return

        if path == "/api/store":
            result = mcp_call("store", {
                "project_key": data.get("project_key", "default"),
                "kind": data.get("kind", "semantic"),
                "content": data.get("content", ""),
                "tags": data.get("tags", []),
                "importance": data.get("importance", 0.5),
                "source": "dashboard",
            })
            self._json(result)
        elif path == "/api/delete":
            mid = data.get("memory_id", "")
            if not mid:
                self._json({"error": "memory_id required"}, 400)
                return
            result = mcp_call("delete", {"memory_id": mid, "reason": "Dashboard deletion"})
            self._json(result)
        else:
            self._json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        # Quieter logs
        if "200" not in str(args):
            print(f"[dashboard] {args[0]}")


# ─── HTML Dashboard ─────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synapse Memory Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-primary: #0a0a0f;
    --bg-secondary: #12121a;
    --bg-card: #1a1a2e;
    --bg-card-hover: #22223a;
    --border: #2a2a3e;
    --text-primary: #e8e8f0;
    --text-secondary: #9898b8;
    --text-muted: #6868a0;
    --accent: #6c5ce7;
    --accent-glow: rgba(108, 92, 231, 0.3);
    --accent-green: #00cec9;
    --accent-red: #ff7675;
    --accent-yellow: #fdcb6e;
    --accent-blue: #74b9ff;
    --radius: 12px;
    --radius-sm: 8px;
    --shadow: 0 8px 32px rgba(0,0,0,0.4);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Header ─────────────────────────────────── */
  .header {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(20px);
  }

  .header-left { display: flex; align-items: center; gap: 16px; }

  .logo {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, var(--accent), var(--accent-green));
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 800;
    color: white;
    box-shadow: 0 0 20px var(--accent-glow);
  }

  .logo-text { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
  .logo-text span { color: var(--accent); }

  .status-badge {
    display: flex; align-items: center; gap: 6px;
    padding: 4px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 500;
  }
  .status-badge.online { background: rgba(0, 206, 201, 0.15); color: var(--accent-green); }
  .status-badge.online .dot { background: var(--accent-green); }
  .status-badge.offline { background: rgba(255, 118, 117, 0.15); color: var(--accent-red); }
  .status-badge.offline .dot { background: var(--accent-red); }
  .dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; animation: pulse 2s infinite; }

  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  .header-right { display: flex; align-items: center; gap: 12px; }
  .header-info { font-size: 12px; color: var(--text-muted); text-align: right; }

  /* ── Layout ──────────────────────────────────── */
  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px 32px;
  }

  /* ── Stats Grid ───────────────────────────────── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  .stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
  }

  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--accent-green));
    opacity: 0;
    transition: opacity 0.3s ease;
  }

  .stat-card:hover { background: var(--bg-card-hover); transform: translateY(-2px); }
  .stat-card:hover::before { opacity: 1; }
  .stat-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
  .stat-value { font-size: 32px; font-weight: 800; color: var(--text-primary); line-height: 1; }
  .stat-sub { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
  .stat-icon { position: absolute; top: 16px; right: 16px; font-size: 24px; opacity: 0.15; }

  /* ── Main Grid ────────────────────────────────── */
  .main-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 24px;
  }

  @media (max-width: 900px) { .main-grid { grid-template-columns: 1fr; } }

  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .card-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .card-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
  .card-subtitle { font-size: 11px; color: var(--text-muted); }

  .card-body { padding: 16px 20px; }

  /* ── Search ───────────────────────────────────── */
  .search-box {
    display: flex; gap: 8px;
  }

  .search-input {
    flex: 1;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 16px;
    color: var(--text-primary);
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    outline: none;
    transition: border-color 0.3s;
  }

  .search-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
  .search-input::placeholder { color: var(--text-muted); }

  .btn {
    padding: 10px 20px;
    border: none;
    border-radius: var(--radius-sm);
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s ease;
  }

  .btn-primary {
    background: linear-gradient(135deg, var(--accent), #8b7cf7);
    color: white;
  }

  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 20px var(--accent-glow); }

  .btn-danger {
    background: rgba(255, 118, 117, 0.15);
    color: var(--accent-red);
  }

  .btn-danger:hover { background: rgba(255, 118, 117, 0.25); }

  .btn-sm { padding: 6px 12px; font-size: 12px; }

  /* ── Memory List ──────────────────────────────── */
  .memory-list { display: flex; flex-direction: column; gap: 8px; max-height: 500px; overflow-y: auto; }

  .memory-item {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px;
    transition: all 0.2s ease;
    position: relative;
  }

  .memory-item:hover { border-color: var(--accent); background: rgba(108, 92, 231, 0.05); }

  .memory-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 6px;
  }

  .memory-kind {
    font-size: 10px; font-weight: 600; text-transform: uppercase;
    padding: 2px 8px; border-radius: 4px;
    letter-spacing: 0.5px;
  }

  .memory-kind.semantic { background: rgba(108, 92, 231, 0.2); color: var(--accent); }
  .memory-kind.episodic { background: rgba(116, 185, 255, 0.2); color: var(--accent-blue); }
  .memory-kind.working { background: rgba(253, 203, 110, 0.2); color: var(--accent-yellow); }

  .memory-score {
    font-size: 11px; font-weight: 600;
    margin-left: auto;
  }
  .memory-score.high { color: var(--accent-green); }
  .memory-score.med { color: var(--accent-yellow); }
  .memory-score.low { color: var(--text-muted); }

  .memory-text {
    font-size: 13px; line-height: 1.5;
    color: var(--text-primary);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .memory-tags {
    display: flex; gap: 4px; flex-wrap: wrap;
    margin-top: 8px;
  }

  .memory-tag {
    font-size: 10px; padding: 2px 8px;
    border-radius: 4px;
    background: rgba(104, 104, 160, 0.15);
    color: var(--text-secondary);
  }

  .memory-delete {
    position: absolute; top: 8px; right: 8px;
    opacity: 0; transition: opacity 0.2s;
  }
  .memory-item:hover .memory-delete { opacity: 1; }

  /* ── Store Form ──────────────────────────────── */
  .store-form { display: flex; flex-direction: column; gap: 12px; }

  .form-row { display: flex; gap: 8px; }
  .form-row > * { flex: 1; }

  .form-select {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 16px;
    color: var(--text-primary);
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    outline: none;
    cursor: pointer;
  }

  .form-select:focus { border-color: var(--accent); }

  textarea.search-input {
    resize: vertical;
    min-height: 80px;
  }

  /* ── Loading ──────────────────────────────────── */
  .loading {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
    font-size: 14px;
  }

  .spinner {
    width: 24px; height: 24px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 12px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Empty State ──────────────────────────────── */
  .empty-state {
    text-align: center;
    padding: 40px 20px;
    color: var(--text-muted);
  }

  .empty-state-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.3; }
  .empty-state-text { font-size: 14px; }

  /* ── Toast ────────────────────────────────────── */
  .toast-container {
    position: fixed; bottom: 24px; right: 24px;
    z-index: 1000;
    display: flex; flex-direction: column; gap: 8px;
  }

  .toast {
    padding: 12px 20px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 500;
    animation: slideIn 0.3s ease;
    background: var(--bg-card);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    color: var(--text-primary);
  }

  .toast.success { border-left: 3px solid var(--accent-green); }
  .toast.error { border-left: 3px solid var(--accent-red); }

  @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

  /* ── Scrollbar ────────────────────────────────── */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">S</div>
    <div class="logo-text">Synapse <span>Memory</span></div>
    <div class="status-badge online" id="statusBadge">
      <span class="dot"></span>
      <span id="statusText">Connecting...</span>
    </div>
  </div>
  <div class="header-right">
    <div class="header-info">
      <div id="serverHost">—</div>
      <div id="serverVersion" style="font-size:10px">—</div>
    </div>
  </div>
</div>

<div class="container">
  <!-- Stats -->
  <div class="stats-grid" id="statsGrid">
    <div class="stat-card">
      <div class="stat-label">Memories</div>
      <div class="stat-value" id="statMemories">—</div>
      <div class="stat-sub">stored across all projects</div>
      <div class="stat-icon">🧠</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Tenants</div>
      <div class="stat-value" id="statTenants">—</div>
      <div class="stat-sub">active organizations</div>
      <div class="stat-icon">🏢</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Tailscale IP</div>
      <div class="stat-value" id="statTailscale" style="font-size:20px">—</div>
      <div class="stat-sub">mesh network endpoint</div>
      <div class="stat-icon">🔗</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Server</div>
      <div class="stat-value" id="statHostname" style="font-size:20px">—</div>
      <div class="stat-sub" id="statUptime">—</div>
      <div class="stat-icon">⚡</div>
    </div>
  </div>

  <!-- Main Grid -->
  <div class="main-grid">
    <!-- Search / Browse -->
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Memory Browser</div>
          <div class="card-subtitle">Search stored memories</div>
        </div>
      </div>
      <div class="card-body">
        <div class="search-box" style="margin-bottom:12px">
          <input type="text" class="search-input" id="searchInput"
                 placeholder="Search memories..." value=""
                 onkeydown="if(event.key==='Enter') searchMemories()">
          <button class="btn btn-primary" onclick="searchMemories()">Search</button>
          <button class="btn btn-primary" onclick="searchMemories('')" style="background:var(--bg-secondary);color:var(--text-secondary)">All</button>
        </div>
        <div id="memoryResults">
          <div class="loading"><div class="spinner"></div>Loading memories...</div>
        </div>
      </div>
    </div>

    <!-- Store -->
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Store Memory</div>
          <div class="card-subtitle">Save knowledge to the persistent brain</div>
        </div>
      </div>
      <div class="card-body">
        <div class="store-form">
          <div class="form-row">
            <select class="form-select" id="storeKind">
              <option value="semantic">🧠 Semantic (knowledge)</option>
              <option value="episodic">📅 Episodic (events)</option>
              <option value="working">📝 Working (transient)</option>
            </select>
            <select class="form-select" id="storeImportance">
              <option value="0.9">🔴 Critical (0.9)</option>
              <option value="0.7" selected>🟠 Important (0.7)</option>
              <option value="0.5">🟡 Useful (0.5)</option>
              <option value="0.3">🟢 Transient (0.3)</option>
            </select>
          </div>
          <input type="text" class="search-input" id="storeContent"
                 placeholder="What did you learn?" autocomplete="off">
          <input type="text" class="search-input" id="storeTags"
                 placeholder="Tags: auth, security, deploy (comma-separated)" autocomplete="off">
          <button class="btn btn-primary" onclick="storeMemory()">Store Memory</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Rankings -->
  <div class="card">
    <div class="card-header">
      <div>
        <div class="card-title">Memory Rankings</div>
        <div class="card-subtitle">Importance, access frequency, and suggested actions</div>
      </div>
    </div>
    <div class="card-body">
      <div id="rankResults">
        <div class="loading"><div class="spinner"></div>Loading rankings...</div>
      </div>
    </div>
  </div>
</div>

<div class="toast-container" id="toastContainer"></div>

<script>
const API = '';

function toast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

async function api(path, options = {}) {
  const url = `${API}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  return res.json();
}

// ── Load Status ────────────────────────────────
async function loadStatus() {
  try {
    const data = await api('/api/status');
    if (data.ok) {
      document.getElementById('statusBadge').className = 'status-badge online';
      document.getElementById('statusText').textContent = 'Connected';
      document.getElementById('serverHost').textContent = data.tailscale_ip || data.hostname || '?';
      document.getElementById('serverVersion').textContent = `v${data.version} · ${data.embedding_dim}d embeddings`;
      document.getElementById('statMemories').textContent = data.memories ?? '?';
      document.getElementById('statTenants').textContent = data.tenants ?? '?';
      document.getElementById('statTailscale').textContent = data.tailscale_ip || '—';
      document.getElementById('statHostname').textContent = data.hostname || '—';
      document.getElementById('statUptime').textContent = data.time ? new Date(data.time).toLocaleString() : '—';
    } else {
      document.getElementById('statusBadge').className = 'status-badge offline';
      document.getElementById('statusText').textContent = 'Disconnected';
      document.getElementById('serverHost').textContent = 'Offline';
    }
  } catch(e) {
    document.getElementById('statusBadge').className = 'status-badge offline';
    document.getElementById('statusText').textContent = 'Error';
    document.getElementById('serverHost').textContent = e.message;
  }
}

// ── Search ─────────────────────────────────────
async function searchMemories(query) {
  const input = document.getElementById('searchInput');
  const q = query !== undefined ? query : input.value.trim();
  const container = document.getElementById('memoryResults');

  container.innerHTML = '<div class="loading"><div class="spinner"></div>Searching...</div>';

  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&limit=50`);
    const results = data.results || [];

    if (results.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🔍</div><div class="empty-state-text">No memories found${q ? ' for "' + q + '"' : ''}</div></div>`;
      return;
    }

    let html = '<div class="memory-list">';
    for (const m of results) {
      const score = (m.score || 0) * 100;
      const scoreClass = score > 70 ? 'high' : score > 40 ? 'med' : 'low';
      const kind = m.kind || 'episodic';
      const text = m.content_text || '(empty)';
      const tags = Array.isArray(m.tags) ? m.tags : [];
      const mid = m.memory_id || '';

      html += `
        <div class="memory-item">
          <button class="btn btn-danger btn-sm memory-delete" onclick="deleteMemory('${mid}')">✕</button>
          <div class="memory-header">
            <span class="memory-kind ${kind}">${kind}</span>
            <span class="memory-score ${scoreClass}">${score.toFixed(0)}%</span>
          </div>
          <div class="memory-text">${escapeHtml(text)}</div>
          <div class="memory-tags">
            ${tags.map(t => `<span class="memory-tag">${escapeHtml(t)}</span>`).join('')}
          </div>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-text">Error: ${e.message}</div></div>`;
  }
}

// ── Store ──────────────────────────────────────
async function storeMemory() {
  const content = document.getElementById('storeContent').value.trim();
  if (!content) { toast('Please enter memory content', 'error'); return; }

  const kind = document.getElementById('storeKind').value;
  const importance = parseFloat(document.getElementById('storeImportance').value);
  const tagsStr = document.getElementById('storeTags').value.trim();
  const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

  try {
    const result = await api('/api/store', {
      method: 'POST',
      body: JSON.stringify({ content, kind, importance, tags }),
    });

    if (result.ok) {
      toast(`Memory stored (v${result.version || 1})`);
      document.getElementById('storeContent').value = '';
      document.getElementById('storeTags').value = '';
      loadStatus();
      searchMemories('');
    } else {
      toast(`Failed: ${result.error || 'unknown error'}`, 'error');
    }
  } catch(e) {
    toast(`Error: ${e.message}`, 'error');
  }
}

// ── Delete ─────────────────────────────────────
async function deleteMemory(mid) {
  if (!confirm('Delete this memory?')) return;
  try {
    const result = await api('/api/delete', {
      method: 'POST',
      body: JSON.stringify({ memory_id: mid }),
    });
    if (result.ok) {
      toast('Memory deleted');
      searchMemories(document.getElementById('searchInput').value);
      loadStatus();
    } else {
      toast(`Delete failed: ${result.error}`, 'error');
    }
  } catch(e) {
    toast(`Error: ${e.message}`, 'error');
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Rankings ───────────────────────────────────
async function loadRankings() {
  const container = document.getElementById('rankResults');
  try {
    const data = await api('/api/rank');
    const ranked = data.ranked || [];
    if (ranked.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📊</div><div class="empty-state-text">No memories to rank yet. Store some first!</div></div>';
      return;
    }
    let html = '<div class="memory-list">';
    for (const r of ranked.slice(0, 20)) {
      const actionColor = r.suggested_action === 'retain' ? 'var(--accent-green)' :
                          r.suggested_action === 'compress' ? 'var(--accent-yellow)' :
                          r.suggested_action === 'archive' ? 'var(--accent-blue)' : 'var(--text-muted)';
      html += `
        <div class="memory-item">
          <div class="memory-header">
            <span class="memory-kind ${r.kind || 'episodic'}">${r.kind || '?'}</span>
            <span class="memory-score high">${(r.importance_score * 100).toFixed(0)}%</span>
            <span style="margin-left:auto;font-size:11px;color:${actionColor};font-weight:600;text-transform:uppercase">${r.suggested_action}</span>
          </div>
          <div style="display:flex;gap:16px;font-size:11px;color:var(--text-muted);margin-top:4px">
            <span>Base: ${(r.base_importance * 100).toFixed(0)}%</span>
            <span>Decay: ${(r.decay_factor * 100).toFixed(0)}%</span>
            <span>Access: ${r.access_count || 0}x</span>
            <span>Age: ${r.age_days || 0}d</span>
          </div>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-text">Error: ${e.message}</div></div>`;
  }
}

// ── Init ───────────────────────────────────────
loadStatus();
searchMemories('');
loadRankings();

// Auto-refresh every 30s
setInterval(loadStatus, 30000);
</script>
</body>
</html>
"""

# ─── Main ───────────────────────────────────────────────────────────

def get_tailscale_ip():
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            self_host = data.get("Self", {})
            ips = self_host.get("TailscaleIPs", [])
            return ips[0] if ips else None
    except Exception:
        pass
    return None

if __name__ == "__main__":
    ts_ip = get_tailscale_ip() or DASHBOARD_HOST
    server = HTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), DashboardHandler)
    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║  Synapse Memory Dashboard                        ║")
    print(f"║                                                  ║")
    print(f"║  Server:  http://{DASHBOARD_HOST}:{DASHBOARD_PORT}                       ║")
    print(f"║  MCP:     {SYNAPSE_URL}  ║")
    print(f"║  Host:    {ts_ip} (this machine)                  ║")
    print(f"║                                                  ║")
    print(f"║  Open in browser:                                ║")
    print(f"║    http://localhost:{DASHBOARD_PORT}                        ║")
    print(f"║    http://{ts_ip}:{DASHBOARD_PORT}  (Tailscale)              ║")
    print(f"╚══════════════════════════════════════════════════╝")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down...")
        server.server_close()
