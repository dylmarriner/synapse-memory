import { stringEnum } from "openclaw/plugin-sdk/channel-actions";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { resolveLivePluginConfigObject } from "openclaw/plugin-sdk/plugin-config-runtime";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  type AnyAgentTool,
  type OpenClawPluginApi,
  type OpenClawPluginConfigSchema,
  type OpenClawPluginToolContext,
} from "openclaw/plugin-sdk/plugin-entry";
import { Static, Type } from "typebox";
import { SYNAPSE_AGENT_GUIDANCE } from "./prompt-guidance.js";

// ─── Config Schema ────────────────────────────────────────────────

const SYNAPSE_DEFAULT_SERVER_URL = "http://100.91.55.113:8765/mcp";

const SynapseConfigSchema = Type.Object(
  {
    serverUrl: Type.Optional(
      Type.String({ description: "Synapse MCP server URL", default: SYNAPSE_DEFAULT_SERVER_URL }),
    ),
    apiKey: Type.Optional(Type.String({ description: "Tenant API key", default: "" })),
    defaultProjectKey: Type.Optional(
      Type.String({ description: "Default project key", default: "default" }),
    ),
    maxRetrieveResults: Type.Optional(
      Type.Number({ description: "Max retrieve results", default: 10, minimum: 1, maximum: 100 }),
    ),
  },
  { additionalProperties: false },
);

export type SynapseConfig = Static<typeof SynapseConfigSchema>;

// ─── Plugin Entry ─────────────────────────────────────────────────

export default definePluginEntry({
  id: "synapse",
  name: "Synapse Memory",
  description:
    "Enterprise-grade multi-tenant AI memory backbone with persistent, cross-device, event-sourced memory for agents and tools.",
  configSchema: SynapseConfigSchema,
  register: registerSynapsePlugin,
});

// ─── Session Cache ────────────────────────────────────────────────

const sessions = new Map<string, { id: string; expiresAt: number }>();

async function ensureSession(serverUrl: string): Promise<string> {
  const now = Date.now();
  const cached = sessions.get(serverUrl);
  if (cached && now < cached.expiresAt) return cached.id;

  const resp = await fetch(serverUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "openclaw-synapse", version: "0.1.0" } },
    }),
  });

  const sessionId = resp.headers.get("mcp-session-id") ?? "";
  if (!sessionId) throw new Error("Synapse server did not return MCP session ID");

  sessions.set(serverUrl, { id: sessionId, expiresAt: now + 14 * 60 * 1000 });
  return sessionId;
}

async function callServer(
  serverUrl: string, tool: string, args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const sessionId = await ensureSession(serverUrl);
  const resp = await fetch(serverUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", "Mcp-Session-Id": sessionId },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool, arguments: args } }),
  });
  const data = (await resp.json()) as {
    result?: { content?: Array<{ type: string; text: string }>; isError?: boolean };
    error?: { message: string };
  };
  if (data.error) throw new Error(`Synapse MCP error: ${data.error.message}`);
  const text = data.result?.content?.[0]?.text;
  if (!text) return { ok: false, error: "Empty response from Synapse server" };
  try { return JSON.parse(text) as Record<string, unknown>; }
  catch { return { ok: true, text }; }
}

function resolveConfig(api: OpenClawPluginApi): SynapseConfig {
  return (resolveLivePluginConfigObject(
    api.runtime.config?.current ? () => api.runtime.config.current() as OpenClawConfig : undefined,
    "synapse",
    api.pluginConfig as Record<string, unknown>,
  ) ?? {}) as SynapseConfig;
}

// ─── Plugin Registration ──────────────────────────────────────────

export function registerSynapsePlugin(api: OpenClawPluginApi): void {
  interface ToolDef {
    name: string;
    mcpTool: string;
    description: string;
    params: Record<string, unknown>;
    format?: (result: Record<string, unknown>) => string;
  }

  const tools: ToolDef[] = [
    {
      name: "synapse_store",
      mcpTool: "store",
      description: "Store a durable memory (conventions, gotchas, architecture, fixes, commands). Memories persist across sessions and devices.",
      params: {
        type: "object",
        properties: {
          content: { type: "string", description: "The memory content text" },
          project_key: { type: "string", description: "Project key (default: from config)" },
          kind: { type: "string", enum: ["working", "episodic", "semantic"], default: "episodic", description: "Memory kind" },
          tags: { type: "array", items: { type: "string" }, description: "Tags for categorization" },
          importance: { type: "number", default: 0.5, minimum: 0, maximum: 1, description: "Importance 0.0-1.0" },
        },
        required: ["content"],
      },
      format: (r) => r.ok ? `Stored: ${r.memory_id} v${r.version ?? 1}` : `Failed: ${r.error}`,
    },
    {
      name: "synapse_retrieve",
      mcpTool: "retrieve",
      description: "Search memory using hybrid keyword + semantic retrieval. Returns ranked results with relevance scores.",
      params: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
          project_key: { type: "string", description: "Scope to project (default: from config)" },
          kinds: { type: "array", items: { type: "string" }, description: "Filter by kinds" },
          limit: { type: "number", default: 10, minimum: 1, maximum: 100, description: "Max results" },
        },
        required: ["query"],
      },
      format: (r) => {
        if (!r.ok) return `Retrieval failed: ${r.error}`;
        const results = (r.results ?? []) as Array<Record<string, unknown>>;
        if (results.length === 0) return "No matching memories found.";
        const lines = [`Found ${r.count ?? results.length} memories:`];
        for (const m of results.slice(0, 10)) {
          lines.push(`  [${((m.score as number ?? 0) * 100).toFixed(0)}%] ${(m.content_text ?? "").toString().slice(0, 120)}`);
          lines.push(`       kind=${m.kind} tags=[${(m.tags as string[] ?? []).slice(0, 5).join(", ")}]`);
        }
        return lines.join("\n");
      },
    },
    {
      name: "synapse_update",
      mcpTool: "update",
      description: "Update an existing memory. Supports merge (append), overwrite, or append strategies.",
      params: {
        type: "object",
        properties: {
          memory_id: { type: "string", description: "Memory ID to update" },
          content: { type: "string", description: "New content or content to append" },
          merge_strategy: { type: "string", enum: ["merge", "overwrite", "append"], default: "merge" },
        },
        required: ["memory_id", "content"],
      },
      format: (r) => r.ok ? `Updated: v${r.version ?? "?"}` : `Update failed: ${r.error}`,
    },
    {
      name: "synapse_delete",
      mcpTool: "delete",
      description: "Delete a memory by ID.",
      params: {
        type: "object",
        properties: {
          memory_id: { type: "string", description: "Memory ID to delete" },
          reason: { type: "string", description: "Optional deletion reason" },
        },
        required: ["memory_id"],
      },
      format: (r) => r.ok ? "Deleted." : `Delete failed: ${r.error}`,
    },
    {
      name: "synapse_context",
      mcpTool: "context",
      description: "Get an optimized context pack for agent prompt injection. Returns pre-compressed, ranked memories matching the query.",
      params: {
        type: "object",
        properties: {
          query: { type: "string", description: "What the agent is about to work on" },
          project_key: { type: "string", description: "Project scope" },
          limit: { type: "number", default: 5, description: "Max context items" },
        },
      },
      format: (r) => {
        if (!r.ok) return `Context failed: ${r.error}`;
        const memories = (r.memories ?? []) as Array<Record<string, unknown>>;
        const lines = [`Context Pack — ${r.project_key ?? "default"}`, `  Tokens saved: ${r.tokens_saved ?? 0} (ratio: ${(((r.compression_ratio as number ?? 0)) * 100).toFixed(1)}%)`];
        for (const m of memories.slice(0, 10)) {
          lines.push(`  [${((m.score as number ?? 0) * 100).toFixed(0)}%] ${(m.content_text ?? "").toString().slice(0, 200)}`);
        }
        return lines.join("\n");
      },
    },
    {
      name: "synapse_rank",
      mcpTool: "rank",
      description: "Rank memories by importance, access frequency, and decay. Shows retain/compress/archive/evict suggestions.",
      params: {
        type: "object",
        properties: {
          project_key: { type: "string", description: "Project scope" },
          limit: { type: "number", default: 20 },
        },
      },
      format: (r) => {
        if (!r.ok) return `Rank failed: ${r.error}`;
        const ranked = (r.ranked ?? []) as Array<Record<string, unknown>>;
        return ranked.map((i) => `  ${(i.importance_score as number ?? 0).toFixed(3)} ${i.suggested_action} (${i.kind ?? "?"})`).join("\n");
      },
    },
    {
      name: "synapse_embed",
      mcpTool: "embed",
      description: "Generate embeddings for a batch of texts.",
      params: {
        type: "object",
        properties: {
          texts: { type: "array", items: { type: "string" }, description: "Texts to embed (max 100)" },
        },
        required: ["texts"],
      },
      format: (r) => r.ok ? `${r.count}x${r.dimensions}d embeddings` : `Embed failed: ${r.error}`,
    },
    {
      name: "synapse_compress",
      mcpTool: "compress",
      description: "Compress memories: deduplicate, summarize, or prune low-value entries.",
      params: {
        type: "object",
        properties: {
          memory_ids: { type: "array", items: { type: "string" }, description: "Memory IDs to compress" },
          strategy: { type: "string", enum: ["deduplicate", "summarize", "prune_low_value"], default: "deduplicate" },
          max_tokens: { type: "number", description: "Target max tokens" },
        },
        required: ["memory_ids"],
      },
      format: (r) => r.ok ? `Compressed ${r.compressed?.length ?? 0} items, evicted ${r.evicted_ids?.length ?? 0}` : `Compress failed: ${r.error}`,
    },
    {
      name: "synapse_memory",
      mcpTool: "health",
      description: "Get Synapse memory server status and usage statistics.",
      params: { type: "object", properties: {} },
      format: (r) => {
        if (!r.ok) return `Status check failed: ${r.error}`;
        const lines = [
          `Status: ${r.ok ? "Operational" : "Degraded"}`,
          r.tailscale_ip ? `  Tailscale: ${r.tailscale_ip}` : null,
          r.hostname ? `  Host: ${r.hostname}` : null,
          r.memories !== undefined ? `  Memories: ${r.memories}` : null,
          r.tenants !== undefined ? `  Tenants: ${r.tenants}` : null,
          r.devices !== undefined ? `  Devices: ${r.devices}` : null,
          r.version ? `  Version: ${r.version}` : null,
        ].filter(Boolean).join("\n");
        return lines;
      },
    },
  ];

  for (const def of tools) {
    api.registerTool(
      (_ctx) => ({
        name: def.name,
        label: def.name.replace("synapse_", "Synapse ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        description: def.description,
        parameters: def.params,
        execute: async (_toolCallId, rawParams) => {
          const cfg = resolveConfig(api);
          const args = rawParams as Record<string, unknown>;
          // Inject API key and defaults
          const mcpArgs: Record<string, unknown> = { api_key: cfg.apiKey ?? "" };
          if (args.project_key) mcpArgs.project_key = args.project_key;
          else if (cfg.defaultProjectKey) mcpArgs.project_key = cfg.defaultProjectKey;
          for (const [k, v] of Object.entries(args)) {
            if (k !== "project_key") mcpArgs[k] = v;
          }
          try {
            const result = await callServer(cfg.serverUrl ?? SYNAPSE_DEFAULT_SERVER_URL, def.mcpTool, mcpArgs);
            if ((result.ok as boolean) === false) {
              return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }], isError: true };
            }
            const formatted = def.format ? def.format(result) : JSON.stringify(result, null, 2);
            return { content: [{ type: "text", text: formatted }], isError: false };
          } catch (error) {
            const msg = error instanceof Error ? error.message : "Unknown error";
            return { content: [{ type: "text", text: `Synapse error: ${msg}` }], isError: true };
          }
        },
      }),
      { name: def.name },
    );
  }

  // Agent guidance
  api.on("before_prompt_build", async () => ({
    prependSystemContext: SYNAPSE_AGENT_GUIDANCE,
  }));
}
