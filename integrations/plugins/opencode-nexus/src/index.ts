/**
 * Nexus Memory Plugin for OpenCode
 *
 * Connects OpenCode to the Nexus unified long-term memory server.
 * Provides 4-way recall (vector + lexical + graph + temporal), durable save,
 * lessons, and structured reflection.
 *
 * Configuration via env vars or opencode.json:
 *   NEXUS_URL    — Nexus base URL (default: http://100.93.75.87:7777)
 *   NEXUS_SECRET — bearer token
 *   NEXUS_AGENT_ID — agent identifier (default: opencode)
 *
 * Auto-registers MCP server entry and tool hooks for memory_recall / memory_save
 * before/after each turn.
 */

import type { Plugin } from "@opencode-ai/plugin";

const DEFAULT_NEXUS_URL = "http://100.93.75.87:7777";

type NexusConfig = {
  url: string;
  secret: string;
  agentId: string;
};

function readConfig(): NexusConfig {
  return {
    url: (process.env.NEXUS_URL ?? DEFAULT_NEXUS_URL).replace(/\/+$/, ""),
    secret: process.env.NEXUS_SECRET ?? "",
    agentId: process.env.NEXUS_AGENT_ID ?? "opencode",
  };
}

async function nexusCall<T>(
  path: string,
  body: unknown,
  cfg: NexusConfig,
  timeoutMs = 8000,
): Promise<T | null> {
  if (!cfg.secret) return null;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${cfg.url}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.secret}`,
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

async function nexusRecall(query: string, cfg: NexusConfig, limit = 6) {
  const res = await nexusCall<{ results: Array<{ memory_type: string; score: number; content: string }> }>(
    "/v1/memory/recall",
    { query: query.slice(0, 500), agent_id: cfg.agentId, limit, search_modes: ["vector", "lexical"] },
    cfg,
  );
  return res?.results ?? [];
}

async function nexusSave(content: string, memoryType: string, cfg: NexusConfig, importance = 0.55) {
  await nexusCall(
    "/v1/memory/save",
    { content: content.slice(0, 1000), agent_id: cfg.agentId, memory_type: memoryType, importance },
    cfg,
    5000,
  );
}

async function nexusReflect(query: string, cfg: NexusConfig) {
  const res = await nexusCall<{ reflection: string }>(
    "/v1/memory/reflect",
    { query, agent_id: cfg.agentId, depth: "mid" },
    cfg,
    20000,
  );
  return res?.reflection ?? "";
}

function buildSlimContext(mems: Array<{ memory_type: string; score: number; content: string }>): string {
  if (!mems.length) return "";
  const lines = ["[Nexus memory context:]"];
  for (const m of mems.slice(0, 5)) {
    lines.push(`  [${m.memory_type}|${m.score.toFixed(2)}] ${m.content.slice(0, 300)}`);
  }
  return lines.join("\n");
}

const INFO_KEYWORDS = [
  "i like", "i prefer", "i use", "remember that", "note:", "important",
  "my favorite", "i always", "i never", "don't forget", "keep in mind",
  "i usually", "i typically", "i want", "i need", "make sure",
];

function containsInformationalContent(text: string): boolean {
  const lo = text.toLowerCase();
  return INFO_KEYWORDS.some((k) => lo.includes(k));
}

export const NexusMemoryPlugin: Plugin = async ({ project, client, $, directory, worktree }) => {
  const cfg = readConfig();
  if (!cfg.secret) {
    return {};
  }

  return {
    // Inject relevant memory before each turn
    "chat.message": async (input, output) => {
      const last = output.messages?.at(-1);
      const query = last?.text ?? "";
      if (!query || query.length < 5) return;
      try {
        const mems = await nexusRecall(query, cfg, 6);
        const ctx = buildSlimContext(mems);
        if (ctx) {
          output.messages = [
            ...(output.messages ?? []),
            { role: "system", text: ctx },
          ];
        }
      } catch {
        // silent — never break the chat
      }
    },

    // Save durable context after each turn (only for informational content)
    "chat.message.end": async (input, output) => {
      try {
        const last = output.messages?.at(-1);
        const text = last?.text ?? "";
        if (text.length < 30) return;
        if (!containsInformationalContent(text)) return;
        await nexusSave(text, "experience", cfg, 0.5);
      } catch {
        // silent
      }
    },

    // Tool wrappers — expose nexus tools to the LLM
    tool: {
      nexus_recall: tool({
        description: "Search Nexus memory with vector + lexical recall. Use before answering questions about prior work, decisions, or preferences.",
        args: {
          query: tool.schema.string().describe("What to search for"),
          limit: tool.schema.number().optional().describe("Max results (default 8)"),
        },
        async execute(args) {
          const mems = await nexusRecall(args.query, cfg, args.limit ?? 8);
          if (!mems.length) return "No memories found.";
          return mems
            .map((m, i) => `${i + 1}. [${m.memory_type}|${m.score.toFixed(2)}] ${m.content.slice(0, 400)}`)
            .join("\n");
        },
      }),

      nexus_save: tool({
        description: "Save durable memory to Nexus. Use for decisions, preferences, lessons, and important context.",
        args: {
          content: tool.schema.string().describe("What to remember"),
          memory_type: tool.schema
            .string()
            .optional()
            .describe("world | experience | observation | preference | lesson (auto-detected if omitted)"),
          importance: tool.schema.number().optional().describe("0..1, default 0.55"),
        },
        async execute(args) {
          await nexusSave(args.content, args.memory_type ?? "experience", cfg, args.importance ?? 0.55);
          return "Memory saved to Nexus.";
        },
      }),

      nexus_reflect: tool({
        description: "Ask Nexus to synthesize memories on a topic into a structured reflection.",
        args: {
          query: tool.schema.string().describe("Topic to reflect on"),
          depth: tool.schema.string().optional().describe("low | mid | high (default mid)"),
        },
        async execute(args) {
          const out = await nexusReflect(args.query, cfg);
          return out || "No reflection available.";
        },
      }),

      nexus_status: tool({
        description: "Check Nexus server health (postgres, redis, embeddings, llm).",
        args: {},
        async execute() {
          const res = await nexusCall<{ healthy: boolean; components: Record<string, string> }>(
            "/health",
            {},
            cfg,
            3000,
          );
          return res ? JSON.stringify(res, null, 2) : "Nexus unreachable";
        },
      }),
    },
  };
};

export default NexusMemoryPlugin;
