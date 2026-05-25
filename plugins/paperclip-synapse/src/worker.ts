/**
 * Synapse Memory adapter plugin for Paperclip.
 *
 * Registers as an adapter plugin that provides memory tools
 * by proxying to the Synapse MCP server.
 */

import { definePlugin } from "@paperclipai/plugin-sdk";

const SYNAPSE_SERVER = process.env.SYNAPSE_SERVER_URL ?? "http://100.91.55.113:8765/mcp";
const SYNAPSE_API_KEY = process.env.SYNAPSE_API_KEY ?? "";

interface SessionCache {
  id: string;
  expiresAt: number;
}

let session: SessionCache | null = null;

async function ensureSession(): Promise<string> {
  const now = Date.now();
  if (session && now < session.expiresAt) return session.id;

  const resp = await fetch(SYNAPSE_SERVER, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "paperclip-synapse-adapter", version: "0.1.0" },
      },
    }),
  });

  const id = resp.headers.get("mcp-session-id") ?? "";
  if (!id) throw new Error("Failed to get MCP session");
  session = { id, expiresAt: now + 840_000 };
  return id;
}

async function callServer(
  tool: string,
  args: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const sessionId = await ensureSession();
  const callArgs = { ...args };
  if (SYNAPSE_API_KEY) callArgs.api_key = SYNAPSE_API_KEY;

  const resp = await fetch(SYNAPSE_SERVER, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Mcp-Session-Id": sessionId,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: tool, arguments: callArgs },
    }),
  });

  const data = (await resp.json()) as {
    result?: { content?: { text: string }[] };
    error?: { message: string };
  };

  if (data.error) throw new Error(data.error.message);
  const text = data.result?.content?.[0]?.text;
  if (!text) return { ok: false, error: "Empty response" };
  return JSON.parse(text);
}

export default definePlugin({
  async setup(ctx) {
    ctx.logger.info("Synapse Memory adapter starting...");

    // Register memory tools
    ctx.tools.register("synapse_store", async (params, context) => {
      const result = await callServer("store", {
        project_key: params.projectKey ?? "default",
        kind: params.kind ?? "semantic",
        content: params.content,
        tags: params.tags ?? [],
        importance: params.importance ?? 0.5,
        source: "paperclip",
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("synapse_retrieve", async (params) => {
      const result = await callServer("retrieve", {
        query: params.query,
        project_key: params.projectKey ?? "default",
        limit: params.limit ?? 10,
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("synapse_context", async (params) => {
      const result = await callServer("context", {
        query: params.query ?? "",
        project_key: params.projectKey ?? "default",
        limit: params.limit ?? 5,
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("synapse_health", async () => {
      const result = await callServer("health", {});
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.logger.info("Synapse Memory adapter ready — 4 tools registered");
  },

  async onHealth() {
    try {
      const h = await callServer("health", {});
      return {
        status: h.ok ? "ok" : "degraded",
        details: { memories: h.memories, tailscale: h.tailscale_ip },
      };
    } catch {
      return { status: "error", message: "Cannot reach Synapse server" };
    }
  },
});
