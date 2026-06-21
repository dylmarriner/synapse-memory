/**
 * Nexus Memory Plugin for OpenClaw
 * Provides long-term memory via the Nexus unified memory server.
 * Uses built-in Node.js https module — zero extra dependencies.
 * Optimized for token efficiency with conditional save and slim context injection.
 */

import { request as httpsRequest } from "node:https";
import { request as httpRequest } from "node:http";

// ── Config ────────────────────────────────────────────────────────────────

type NexusConfig = {
  nexusUrl: string;
  nexusSecret: string;
  agentId: string;
  autoCapture: boolean;
  autoRecall: boolean;
};

function getConfig(): NexusConfig {
  return {
    nexusUrl: process.env.NEXUS_URL ?? "http://100.93.75.87:7777",
    nexusSecret: process.env.NEXUS_SECRET ?? "$NEXUS_SECRET",
    agentId: process.env.NEXUS_AGENT_ID ?? "openclaw",
    autoCapture: true,
    autoRecall: true,
  };
}

// Keywords that indicate new information worth remembering
const INFORMATION_KEYWORDS = [
  "i like", "i prefer", "i use", "remember that", "note:", "important",
  "my favorite", "i always", "i never", "don't forget", "keep in mind",
  "i usually", "i typically", "i want", "i need", "make sure"
];

function containsInformationalContent(content: string): boolean {
  const contentLower = content.toLowerCase();
  return INFORMATION_KEYWORDS.some(keyword => contentLower.includes(keyword));
}

// ── HTTP helpers ──────────────────────────────────────────────────────────

function nexusPost<T>(path: string, body: unknown, timeoutMs = 8000): Promise<T> {
  const cfg = getConfig();
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const url = new URL(cfg.nexusUrl + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cfg.nexusSecret}`,
        "Content-Length": Buffer.byteLength(data),
      },
      timeout: timeoutMs,
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(raw)); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.write(data);
    req.end();
  });
}

function nexusGet<T>(path: string, timeoutMs = 6000): Promise<T> {
  const cfg = getConfig();
  return new Promise((resolve, reject) => {
    const url = new URL(cfg.nexusUrl + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "GET",
      headers: { "Authorization": `Bearer ${cfg.nexusSecret}` },
      timeout: timeoutMs,
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(raw)); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.end();
  });
}

// ── Nexus API calls ───────────────────────────────────────────────────────

async function nexusRecall(query: string, limit = 8): Promise<any[]> {
  const cfg = getConfig();
  try {
    const res: any = await nexusPost("/v1/memory/recall", {
      query: query.slice(0, 500),
      agent_id: cfg.agentId,
      limit,
      search_modes: ["vector", "lexical"],
    });
    return res?.results ?? [];
  } catch { return []; }
}

async function nexusSave(content: string, memoryType?: string, importance = 0.55): Promise<void> {
  const cfg = getConfig();
  try {
    await nexusPost("/v1/memory/save", {
      content: content.slice(0, 1000),
      agent_id: cfg.agentId,
      memory_type: memoryType,
      importance,
    });
  } catch { /* silent */ }
}

async function nexusReflect(query: string): Promise<string> {
  try {
    const res: any = await nexusPost("/v1/memory/reflect", {
      query,
      agent_id: getConfig().agentId,
      depth: "mid",
    }, 20000);
    return res?.reflection ?? "";
  } catch { return ""; }
}

async function updateAgentActivity(model?: string, capabilities?: string[]): Promise<boolean> {
  const cfg = getConfig();
  try {
    const body: any = {};
    if (model) body.model = model;
    if (capabilities) body.capabilities = capabilities;
    
    await nexusPost(`/v1/agents/${cfg.agentId}/update`, body, 5000);
    return true;
  } catch { return false; }
}

async function getAgentContext(tokens = 2000): Promise<any> {
  const cfg = getConfig();
  try {
    return await nexusGet(`/v1/agents/${cfg.agentId}/context?tokens=${tokens}`);
  } catch { return null; }
}

// ── Optimized context injection ─────────────────────────────────────────────

async function buildSlimContext(): Promise<string> {
  """Build slim context: only summary + top 3 conclusions (saves 400-800 tokens)."""
  try {
    const ctx = await getAgentContext(1500);
    if (!ctx) return "";

    const lines = ["[Nexus memory context:]"];

    // Always include summary
    if (ctx.summary) {
      lines.push(`Summary: ${ctx.summary}`);
    }

    // Only top 3 most important conclusions
    if (ctx.conclusions && ctx.conclusions.length > 0) {
      lines.push("Key conclusions:");
      ctx.conclusions.slice(0, 3).forEach((c: string) => {
        lines.push(`  - ${c}`);
      });
    }

    return lines.join("\n");
  } catch { return ""; }
}

// ── Plugin entry point ────────────────────────────────────────────────────

export async function onBeforeResponse(context: {
  userMessage: string;
  injectContext: (text: string) => void;
}): Promise<void> {
  const cfg = getConfig();
  if (!cfg.autoRecall) return;
  
  // Use slim context injection instead of full recall
  const slimContext = await buildSlimContext();
  if (slimContext) {
    context.injectContext(slimContext);
  }
}

export async function onAfterResponse(context: {
  userMessage: string;
  assistantMessage: string;
}): Promise<void> {
  const cfg = getConfig();
  if (!cfg.autoCapture) return;
  
  const text = context.userMessage.slice(0, 600);
  if (text.length < 30) return;
  
  // Conditional save: only if contains informational keywords
  if (!containsInformationalContent(text)) {
    console.log("[Nexus] Skipped save (no informational keywords)");
    return;
  }
  
  await nexusSave(text, "experience", 0.5);
  console.log("[Nexus] Saved memory (informational content detected)");
  
  // Update agent activity for registry
  await updateAgentActivity();
}

// Standard MCP-style tool handlers (matching contracts in openclaw.plugin.json)
export const tools = {
  async memory_recall(args: { query: string; limit?: number }) {
    const results = await nexusRecall(args.query, args.limit ?? 8);
    if (!results.length) return { text: "No memories found." };
    const lines = results.map(m =>
      `[${m.memory_type}] score=${(m.score ?? 0).toFixed(2)}  ${(m.content ?? "").slice(0, 400)}`
    );
    return { text: `Found ${results.length} memories:\n${lines.join("\n")}` };
  },

  async memory_store(args: { content: string; type?: string; importance?: number }) {
    await nexusSave(args.content, args.type, args.importance ?? 0.6);
    return { text: "Memory saved to Nexus." };
  },

  async memory_forget(args: { query: string }) {
    // Nexus doesn't have a direct forget-by-query — return guidance
    return { text: "Use the Nexus dashboard at http://100.93.75.87:7777/ to delete specific memories." };
  },
};