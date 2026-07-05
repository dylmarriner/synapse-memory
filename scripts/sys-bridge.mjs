#!/usr/bin/env node
/**
 * Nexus sys Bridge
 * Wraps the sys MCP server and exposes it as a simple HTTP API.
 *
 * POST /call  { project, tool, args }  →  { result } | { error }
 * GET  /health                          →  { ok, projects }
 *
 * Maintains one long-lived subprocess per project, recycled after 10 min idle.
 */

import http from "node:http";
import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";

const PORT = parseInt(process.env.BRIDGE_PORT ?? "7778");
const NEXUS_CORE_DIR = process.env.NEXUS_CORE_DIR ?? `${process.env.HOME}/.nexus_core`;
const NEXUS_EXT_JS = process.env.NEXUS_EXT_JS ?? "";
const IDLE_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

// ── Process pool ──────────────────────────────────────────────────────────────

const pool = new Map(); // project → { proc, pending, idleTimer }

function getEnvFile(project) {
  return path.join(NEXUS_CORE_DIR, project, "mcp-secret-env.json");
}

function listProjects() {
  try {
    const pj = JSON.parse(readFileSync(path.join(NEXUS_CORE_DIR, "projects.json"), "utf8"));
    return [...new Set(Object.values(pj))];
  } catch {
    return [];
  }
}

function spawnWorker(project) {
  const envFile = getEnvFile(project);
  if (!existsSync(envFile)) throw new Error(`No env file for project: ${project}`);
  if (!existsSync(NEXUS_EXT_JS)) throw new Error(`Nexus MCP server not found: ${NEXUS_EXT_JS}`);

  const proc = spawn("node", [NEXUS_EXT_JS], {
    env: { ...process.env, BRAINSYNC_ENV_FILE: envFile },
    stdio: ["pipe", "pipe", "pipe"],
  });

  const state = { proc, pending: new Map(), idleTimer: null, msgId: 1, buf: "" };

  proc.stdout.on("data", (chunk) => {
    state.buf += chunk.toString();
    let nl;
    while ((nl = state.buf.indexOf("\n")) !== -1) {
      const line = state.buf.slice(0, nl).trim();
      state.buf = state.buf.slice(nl + 1);
      if (!line) continue;
      try {
        const msg = JSON.parse(line);
        const cb = state.pending.get(msg.id);
        if (cb) { state.pending.delete(msg.id); cb(null, msg); }
      } catch { /* ignore non-JSON lines */ }
    }
  });

  proc.on("exit", () => {
    for (const [, cb] of state.pending) cb(new Error("Nexus process exited"));
    pool.delete(project);
  });

  // MCP initialize handshake
  send(state, "initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "nexus-sys", version: "1.0" },
  }).catch(() => {});

  return state;
}

function send(state, method, params) {
  return new Promise((resolve, reject) => {
    const id = state.msgId++;
    state.pending.set(id, (err, msg) => err ? reject(err) : resolve(msg));
    state.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    setTimeout(() => {
      if (state.pending.has(id)) {
        state.pending.delete(id);
        reject(new Error(`Timeout waiting for response to ${method}`));
      }
    }, 15000);
  });
}

function getWorker(project) {
  let state = pool.get(project);
  if (!state || state.proc.exitCode !== null) {
    state = spawnWorker(project);
    pool.set(project, state);
  }
  // Reset idle timer
  clearTimeout(state.idleTimer);
  state.idleTimer = setTimeout(() => {
    const s = pool.get(project);
    if (s) { s.proc.kill(); pool.delete(project); }
  }, IDLE_TIMEOUT_MS);
  return state;
}

async function callTool(project, tool, args) {
  const state = getWorker(project);
  const resp = await send(state, "tools/call", { name: tool, arguments: args ?? {} });
  if (resp.error) throw new Error(resp.error.message ?? JSON.stringify(resp.error));
  const content = resp.result?.content;
  if (Array.isArray(content) && content[0]?.text) {
    try { return JSON.parse(content[0].text); } catch { return { text: content[0].text }; }
  }
  return resp.result ?? {};
}

// ── HTTP server ───────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const send200 = (data) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(data));
  };
  const send4xx = (code, msg) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: msg }));
  };

  if (req.method === "GET" && req.url === "/health") {
    return send200({ ok: true, projects: listProjects(), active: [...pool.keys()] });
  }

  if (req.method === "POST" && req.url === "/call") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      try {
        const { project, tool, args } = JSON.parse(body);
        if (!project || !tool) return send4xx(400, "project and tool required");
        const result = await callTool(project, tool, args);
        send200({ result });
      } catch (e) {
        send4xx(500, e.message);
      }
    });
    return;
  }

  send4xx(404, "Not found");
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Nexus bridge listening on :${PORT}`);
  console.log(`  Core dir: ${NEXUS_CORE_DIR}`);
  console.log(`  MCP ext:  ${NEXUS_EXT_JS}`);
  console.log(`  Projects: ${listProjects().join(", ") || "(none)"}`);
});

process.on("SIGTERM", () => {
  for (const [, s] of pool) s.proc.kill();
  server.close(() => process.exit(0));
});
