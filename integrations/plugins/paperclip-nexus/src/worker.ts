/**
 * Nexus Memory adapter plugin for Paperclip.
 * Proxies to the Nexus MCP server using Bearer token auth.
 */

import { definePlugin } from "@paperclipai/plugin-sdk";

const NEXUS_SERVER = process.env.NEXUS_URL ?? "http://100.93.75.87:7777/mcp";
const NEXUS_SECRET = process.env.NEXUS_SECRET ?? "";
const NEXUS_AGENT  = process.env.NEXUS_AGENT  ?? "paperclip";

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json", Accept: "application/json" };
  if (NEXUS_SECRET) h["Authorization"] = `Bearer ${NEXUS_SECRET}`;
  return h;
}

async function callNexus(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  const resp = await fetch(NEXUS_SERVER, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "tools/call",
      params: { name: tool, arguments: { agent_id: NEXUS_AGENT, ...args } },
    }),
  });

  const data = await resp.json() as {
    result?: { content?: Array<{ text: string }> };
    error?: { message: string };
  };

  if (data.error) throw new Error(data.error.message);
  const text = data.result?.content?.[0]?.text;
  if (!text) return { ok: false, error: "Empty response" };
  try { return JSON.parse(text); } catch { return { text }; }
}

export default definePlugin({
  async setup(ctx) {
    ctx.logger.info("Nexus Memory adapter starting…");

    ctx.tools.register("nexus_save", async (params) => {
      const result = await callNexus("memory_save", {
        content: params.content,
        memory_type: params.kind ?? params.memory_type,
        importance: params.importance ?? 0.5,
        tags: params.tags ?? [],
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("nexus_recall", async (params) => {
      const result = await callNexus("memory_recall", {
        query: params.query,
        limit: params.limit ?? 10,
        memory_types: params.kinds ?? [],
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("nexus_context", async (params) => {
      const result = await callNexus("agent_context", {
        tokens: params.tokens ?? 2000,
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("nexus_reflect", async (params) => {
      const result = await callNexus("memory_reflect", {
        query: params.query,
        depth: params.depth ?? "mid",
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.tools.register("nexus_status", async () => {
      const result = await callNexus("nexus_status", {});
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    });

    ctx.logger.info("Nexus Memory adapter ready — 5 tools registered");
  },

  async onHealth() {
    try {
      const h = await callNexus("nexus_status", {});
      return { status: "ok", details: h };
    } catch {
      return { status: "error", message: "Cannot reach Nexus server" };
    }
  },
});
