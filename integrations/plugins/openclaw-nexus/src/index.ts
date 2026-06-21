import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { resolveLivePluginConfigObject } from "openclaw/plugin-sdk/plugin-config-runtime";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  type OpenClawPluginApi,
  type OpenClawPluginConfigSchema,
} from "openclaw/plugin-sdk/plugin-entry";
import { Static, Type } from "typebox";
import { NEXUS_AGENT_GUIDANCE } from "./prompt-guidance.js";

const NEXUS_DEFAULT_URL = "http://100.93.75.87:7777/mcp";

const NexusConfigSchema = Type.Object(
  {
    serverUrl: Type.Optional(Type.String({ description: "Nexus MCP endpoint", default: NEXUS_DEFAULT_URL })),
    secret: Type.Optional(Type.String({ description: "NEXUS_SECRET bearer token", default: "" })),
    agentId: Type.Optional(Type.String({ description: "Agent ID for this OpenClaw instance", default: "openclaw" })),
    maxResults: Type.Optional(Type.Number({ description: "Max recall results", default: 10, minimum: 1, maximum: 100 })),
  },
  { additionalProperties: false },
);

export type NexusConfig = Static<typeof NexusConfigSchema>;

export default definePluginEntry({
  id: "nexus",
  name: "Nexus Memory",
  description: "Unified AI memory — semantic · lexical · graph · temporal recall. Shared across all agents and devices.",
  configSchema: NexusConfigSchema,
  register: registerNexusPlugin,
});

async function callNexus(
  serverUrl: string, secret: string, tool: string, args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (secret) headers["Authorization"] = `Bearer ${secret}`;

  const resp = await fetch(serverUrl, {
    method: "POST",
    headers,
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool, arguments: args } }),
  });

  const data = await resp.json() as {
    result?: { content?: Array<{ type: string; text: string }> };
    error?: { message: string };
  };

  if (data.error) throw new Error(`Nexus error: ${data.error.message}`);
  const text = data.result?.content?.[0]?.text;
  if (!text) return {};
  try { return JSON.parse(text) as Record<string, unknown>; }
  catch { return { text }; }
}

function resolveConfig(api: OpenClawPluginApi): NexusConfig {
  return (resolveLivePluginConfigObject(
    api.runtime.config?.current ? () => api.runtime.config.current() as OpenClawConfig : undefined,
    "nexus",
    api.pluginConfig as Record<string, unknown>,
  ) ?? {}) as NexusConfig;
}

export function registerNexusPlugin(api: OpenClawPluginApi): void {
  const tools = [
    {
      name: "nexus_save",
      mcpTool: "memory_save",
      description: "Save a memory to Nexus (auto-classifies type, generates embedding). Persists across all devices.",
      params: {
        type: "object",
        properties: {
          content: { type: "string", description: "Memory content" },
          memory_type: { type: "string", enum: ["world", "experience", "observation", "preference", "lesson"] },
          importance: { type: "number", default: 0.5, minimum: 0, maximum: 1 },
          tags: { type: "array", items: { type: "string" } },
        },
        required: ["content"],
      },
      format: (r: Record<string, unknown>) => `Saved ${(r.id as string)?.slice(0, 8)}… | type: ${r.classified_type}`,
    },
    {
      name: "nexus_recall",
      mcpTool: "memory_recall",
      description: "Search memories with 4-way parallel recall (vector + lexical + graph + temporal). Returns ranked results.",
      params: {
        type: "object",
        properties: {
          query: { type: "string" },
          limit: { type: "number", default: 10, minimum: 1, maximum: 100 },
          memory_types: { type: "array", items: { type: "string" } },
        },
        required: ["query"],
      },
      format: (r: Record<string, unknown>) => {
        const results = (r.results ?? []) as Array<Record<string, unknown>>;
        if (!results.length) return "No memories found.";
        return [`Found ${r.total} (modes: ${(r.modes_used as string[])?.join(", ")})`,
          ...results.slice(0, 10).map((m, i) =>
            `${i + 1}. [${m.memory_type}] ${(m.content as string)?.slice(0, 150)}`
          )].join("\n");
      },
    },
    {
      name: "nexus_context",
      mcpTool: "agent_context",
      description: "Get full context for this agent: representation, recent memories, conclusions.",
      params: {
        type: "object",
        properties: {
          tokens: { type: "number", default: 2000 },
        },
      },
      format: (r: Record<string, unknown>) => JSON.stringify(r, null, 2),
    },
    {
      name: "nexus_reflect",
      mcpTool: "memory_reflect",
      description: "LLM-driven synthesis over memories. Returns structured insights and patterns.",
      params: {
        type: "object",
        properties: {
          query: { type: "string" },
          depth: { type: "string", enum: ["low", "mid", "high"], default: "mid" },
        },
        required: ["query"],
      },
      format: (r: Record<string, unknown>) => r.reflection as string ?? JSON.stringify(r),
    },
    {
      name: "nexus_status",
      mcpTool: "nexus_status",
      description: "Check Nexus health (postgres, redis, embeddings, LLM).",
      params: { type: "object", properties: {} },
      format: (r: Record<string, unknown>) => JSON.stringify(r, null, 2),
    },
  ] as const;

  for (const def of tools) {
    api.registerTool(
      (_ctx) => ({
        name: def.name,
        label: def.name.replace("nexus_", "Nexus ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        description: def.description,
        parameters: def.params,
        execute: async (_id, rawParams) => {
          const cfg = resolveConfig(api);
          const serverUrl = cfg.serverUrl ?? NEXUS_DEFAULT_URL;
          const secret = cfg.secret ?? process.env.NEXUS_SECRET ?? "";
          const agentId = cfg.agentId ?? "openclaw";
          const args = { agent_id: agentId, ...(rawParams as Record<string, unknown>) };
          try {
            const result = await callNexus(serverUrl, secret, def.mcpTool, args);
            return { content: [{ type: "text", text: def.format(result) }], isError: false };
          } catch (e) {
            return { content: [{ type: "text", text: (e as Error).message }], isError: true };
          }
        },
      }),
      { name: def.name },
    );
  }

  api.on("before_prompt_build", async () => ({ prependSystemContext: NEXUS_AGENT_GUIDANCE }));
}
