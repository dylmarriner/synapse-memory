const PLUGIN_ID = "nexus-memory";
const DEFAULT_NEXUS_URL = "http://100.93.75.87:7777";
const DEFAULT_AGENT_ID = "openclaw";

function normalizeBaseUrl(value) {
  const raw = typeof value === "string" && value.trim() ? value.trim() : DEFAULT_NEXUS_URL;
  return raw.replace(/\/+$/, "");
}

function getEntryConfig(api, ctx) {
  return (
    ctx?.config?.plugins?.entries?.[PLUGIN_ID]?.config ??
    api?.config?.plugins?.entries?.[PLUGIN_ID]?.config ??
    {}
  );
}

function resolveConfig(api, ctx) {
  const entry = getEntryConfig(api, ctx);
  return {
    nexusUrl: normalizeBaseUrl(entry.nexusUrl ?? process.env.NEXUS_URL),
    nexusSecret: String(entry.nexusSecret ?? process.env.NEXUS_SECRET ?? ""),
    agentId: String(entry.agentId ?? process.env.NEXUS_AGENT_ID ?? DEFAULT_AGENT_ID),
    autoRecall: entry.autoRecall !== false,
    autoCapture: entry.autoCapture !== false,
  };
}

function headers(config, hasBody = false) {
  const result = {};
  if (hasBody) result["content-type"] = "application/json";
  if (config.nexusSecret) result.authorization = `Bearer ${config.nexusSecret}`;
  return result;
}

async function nexusFetchJson(config, path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 8000);
  try {
    const response = await fetch(`${config.nexusUrl}${path}`, {
      method: options.method ?? "GET",
      headers: headers(config, options.body !== undefined),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });

    const text = await response.text();
    let data = null;
    if (text.trim()) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { text };
      }
    }

    if (!response.ok) {
      const message = data?.detail ?? data?.error ?? data?.message ?? response.statusText;
      throw new Error(`Nexus ${response.status}: ${message}`);
    }

    return data;
  } finally {
    clearTimeout(timeout);
  }
}

async function recall(config, params) {
  const data = await nexusFetchJson(config, "/v1/memory/recall", {
    method: "POST",
    timeoutMs: 12000,
    body: {
      query: String(params.query ?? "").slice(0, 1000),
      agent_id: params.agentId ?? config.agentId,
      limit: Number.isFinite(params.limit) ? Math.max(1, Math.min(25, Math.floor(params.limit))) : 8,
      memory_types: Array.isArray(params.memoryTypes) ? params.memoryTypes : [],
      search_modes: Array.isArray(params.searchModes) && params.searchModes.length
        ? params.searchModes
        : ["vector", "lexical", "graph", "temporal"],
    },
  });
  return Array.isArray(data?.results) ? data.results : [];
}

async function saveMemory(config, params) {
  return await nexusFetchJson(config, "/v1/memory/save", {
    method: "POST",
    timeoutMs: 10000,
    body: {
      content: String(params.content ?? "").slice(0, 8000),
      agent_id: params.agentId ?? config.agentId,
      memory_type: params.type ?? params.memoryType ?? "observation",
      importance: Number.isFinite(params.importance) ? params.importance : 0.6,
      tags: Array.isArray(params.tags) ? params.tags : [],
    },
  });
}


function toolJson(value) {
  const text = typeof value?.text === "string" ? value.text : JSON.stringify(value, null, 2);
  return {
    type: "json",
    value,
    text,
  };
}

function formatMemory(memory) {
  const type = memory.memory_type ?? memory.type ?? "memory";
  const score = Number.isFinite(memory.score) ? ` score=${memory.score.toFixed(2)}` : "";
  const content = String(memory.content ?? "").replace(/\s+/g, " ").trim();
  return `[${type}${score}] ${content}`.trim();
}

// ---------------------------------------------------------------------------
// Tool: memory_recall
// ---------------------------------------------------------------------------

function createRecallTool(api) {
  return {
    name: "memory_recall",
    label: "Nexus Memory Recall",
    description: "Search Nexus long-term memory using vector, lexical, graph, and temporal recall. Use this before answering questions about prior work, preferences, decisions, lessons, people, or project context.",
    promptSnippet: "memory_recall: search Nexus long-term memory before answering questions about prior work, preferences, decisions, lessons, people, or project context.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 25 },
        agentId: { type: "string" },
        memoryTypes: { type: "array", items: { type: "string" } },
        searchModes: { type: "array", items: { type: "string", enum: ["vector", "lexical", "graph", "temporal"] } }
      },
      required: ["query"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const results = await recall(config, params);
      return toolJson({
        source: "nexus",
        count: results.length,
        agentId: params.agentId ?? config.agentId,
        results,
        text: results.length ? results.map(formatMemory).join("\n") : "No Nexus memories found."
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_store
// ---------------------------------------------------------------------------

function createStoreTool(api) {
  return {
    name: "memory_store",
    label: "Nexus Memory Store",
    description: "Save a durable memory, lesson, user preference, project fact, or important observation to Nexus long-term memory.",
    promptSnippet: "memory_store: save durable lessons, preferences, project facts, and important observations to Nexus long-term memory.",
    parameters: {
      type: "object",
      properties: {
        content: { type: "string" },
        type: { type: "string" },
        importance: { type: "number", minimum: 0, maximum: 1 },
        tags: { type: "array", items: { type: "string" } },
        agentId: { type: "string" }
      },
      required: ["content"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const saved = await saveMemory(config, params);
      return toolJson({ source: "nexus", saved: true, response: saved, text: "Memory saved to Nexus." });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_forget
// ---------------------------------------------------------------------------

function createForgetTool(api) {
  return {
    name: "memory_forget",
    label: "Nexus Memory Forget",
    description: "Find and delete memories from Nexus matching a search query.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query for memories to remove" },
        limit: { type: "integer", minimum: 1, maximum: 10, description: "Max memories to delete" },
      },
      required: ["query"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const results = await recall(config, { query: params.query, limit: params.limit ?? 5 });
      if (!results.length) {
        return toolJson({ source: "nexus", deleted: 0, text: "No matching memories found to forget." });
      }
      let deleted = 0;
      for (const m of results) {
        if (!m.id) continue;
        try {
          await nexusFetchJson(config, `/v1/browse/memories/${m.id}`, { method: "DELETE", timeoutMs: 5000 });
          deleted++;
        } catch { /* skip failed deletes */ }
      }
      return toolJson({
        source: "nexus",
        deleted,
        total_matched: results.length,
        text: `Deleted ${deleted} of ${results.length} matching memories.`,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_consolidate
// ---------------------------------------------------------------------------

function createConsolidateTool(api) {
  return {
    name: "memory_consolidate",
    label: "Nexus Memory Consolidate",
    description: "Trigger server-side memory consolidation: deduplicates near-identical memories, prunes stale entries, and merges related observations. Run periodically or when memory quality degrades.",
    parameters: {
      type: "object",
      properties: {
        agentId: { type: "string", description: "Agent whose memories to consolidate" },
        dedupThreshold: { type: "number", minimum: 0.5, maximum: 1.0, description: "Similarity threshold for dedup (default 0.85)" },
      },
      required: [],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const result = await nexusFetchJson(config, "/v1/memory/consolidate", {
        method: "POST",
        timeoutMs: 30000,
        body: {
          agent_id: params.agentId ?? config.agentId,
          dedup_threshold: Number.isFinite(params.dedupThreshold) ? params.dedupThreshold : 0.85,
        },
      });
      const merged = result?.merged ?? 0;
      const pruned = result?.pruned ?? 0;
      return toolJson({
        source: "nexus",
        merged,
        pruned,
        details: result,
        text: `Consolidation complete: ${merged} merged, ${pruned} pruned.`,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_reflect
// ---------------------------------------------------------------------------

function createReflectTool(api) {
  return {
    name: "memory_reflect",
    label: "Nexus Memory Reflect",
    description: "Perform deep synthesis over recalled memories to extract patterns, insights, and connections. Use for strategic questions, retrospectives, or when shallow recall isn't enough.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Topic or question to reflect on" },
        agentId: { type: "string" },
        depth: { type: "string", enum: ["mid", "high"], description: "Reflection depth (default mid)" },
      },
      required: ["query"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const result = await nexusFetchJson(config, "/v1/memory/reflect", {
        method: "POST",
        timeoutMs: 20000,
        body: {
          query: String(params.query).slice(0, 1000),
          agent_id: params.agentId ?? config.agentId,
          depth: params.depth === "high" ? "high" : "mid",
        },
      });
      const insights = result?.insights ?? result?.reflection ?? result;
      const text = typeof insights === "string" ? insights : JSON.stringify(insights, null, 2);
      return toolJson({
        source: "nexus",
        query: params.query,
        depth: params.depth ?? "mid",
        insights,
        text,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_context
// ---------------------------------------------------------------------------

function categorizeMemory(memory) {
  const type = (memory.memory_type ?? memory.type ?? "").toLowerCase();
  const content = String(memory.content ?? "").toLowerCase();
  if (type === "preference" || type === "user_preference" || content.includes("prefer")) return "preferences";
  if (type === "decision" || content.includes("decided") || content.includes("chose")) return "decisions";
  if (type === "task" || type === "todo" || content.includes("working on") || content.includes("in progress")) return "active_work";
  return "facts";
}

function createContextTool(api) {
  return {
    name: "memory_context",
    label: "Nexus Context Reconstruction",
    description: "Reconstruct full session context from Nexus memory. Performs a broad 4-way recall (vector + lexical + graph + temporal) and groups results into active_work, decisions, preferences, and facts. Use at session start or when the agent needs full situational awareness.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Context topic (e.g. 'current project state')" },
        agentId: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 50, description: "Max memories to retrieve (default 20)" },
      },
      required: [],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const query = String(params.query ?? "session context active work decisions preferences").slice(0, 1000);
      const limit = Number.isFinite(params.limit) ? Math.max(1, Math.min(50, Math.floor(params.limit))) : 20;

      const results = await recall(config, {
        query,
        limit,
        agentId: params.agentId ?? config.agentId,
        searchModes: ["vector", "lexical", "graph", "temporal"],
      });

      const groups = { active_work: [], decisions: [], preferences: [], facts: [] };
      for (const m of results) {
        const cat = categorizeMemory(m);
        groups[cat].push(formatMemory(m));
      }

      const sections = [];
      if (groups.active_work.length) sections.push(`## Active Work\n${groups.active_work.join("\n")}`);
      if (groups.decisions.length) sections.push(`## Decisions\n${groups.decisions.join("\n")}`);
      if (groups.preferences.length) sections.push(`## Preferences\n${groups.preferences.join("\n")}`);
      if (groups.facts.length) sections.push(`## Facts & Context\n${groups.facts.join("\n")}`);

      const text = sections.length ? sections.join("\n\n") : "No context memories found.";
      return toolJson({
        source: "nexus",
        total: results.length,
        groups: {
          active_work: groups.active_work.length,
          decisions: groups.decisions.length,
          preferences: groups.preferences.length,
          facts: groups.facts.length,
        },
        context_block: text,
        text,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_confirm
// ---------------------------------------------------------------------------

function createConfirmTool(api) {
  return {
    name: "memory_confirm",
    label: "Nexus Memory Confirm",
    description: "Boost trust score for a specific memory by confirming it is accurate and still relevant.",
    parameters: {
      type: "object",
      properties: {
        memoryId: { type: "string", description: "ID of the memory to confirm" },
      },
      required: ["memoryId"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const result = await nexusFetchJson(config, `/v1/memory/${params.memoryId}/confirm`, {
        method: "POST",
        timeoutMs: 5000,
        body: { agent_id: config.agentId },
      });
      return toolJson({
        source: "nexus",
        memoryId: params.memoryId,
        action: "confirmed",
        details: result,
        text: `Memory ${params.memoryId} confirmed — trust score boosted.`,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Tool: memory_contradict
// ---------------------------------------------------------------------------

function createContradictTool(api) {
  return {
    name: "memory_contradict",
    label: "Nexus Memory Contradict",
    description: "Demote trust score for a specific memory by marking it as outdated or inaccurate.",
    parameters: {
      type: "object",
      properties: {
        memoryId: { type: "string", description: "ID of the memory to contradict" },
        reason: { type: "string", description: "Why this memory is being contradicted" },
      },
      required: ["memoryId"],
      additionalProperties: false
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const config = resolveConfig(api, ctx);
      const body = { agent_id: config.agentId };
      if (params.reason) body.reason = String(params.reason).slice(0, 500);
      const result = await nexusFetchJson(config, `/v1/memory/${params.memoryId}/contradict`, {
        method: "POST",
        timeoutMs: 5000,
        body,
      });
      return toolJson({
        source: "nexus",
        memoryId: params.memoryId,
        action: "contradicted",
        details: result,
        text: `Memory ${params.memoryId} contradicted — trust score demoted.`,
      });
    }
  };
}

// ---------------------------------------------------------------------------
// Prompt section builder
// ---------------------------------------------------------------------------

function buildPromptSection({ availableTools }) {
  if (!availableTools?.has?.("memory_recall")) return [];
  const lines = [
    "## Nexus Memory",
    "Before answering questions involving prior work, decisions, dates, people, preferences, lessons, todos, project context, or anything the user may expect you to remember:",
    "- **memory_recall**: search long-term memory with a concise query.",
    "- **memory_store**: save durable lessons, preferences, project facts, and important observations.",
    "- **memory_forget**: remove outdated or incorrect memories.",
  ];
  if (availableTools.has("memory_consolidate")) {
    lines.push("- **memory_consolidate**: deduplicate and prune stale memories periodically.");
  }
  if (availableTools.has("memory_reflect")) {
    lines.push("- **memory_reflect**: deep synthesis over memories for strategic insights and patterns.");
  }
  if (availableTools.has("memory_context")) {
    lines.push("- **memory_context**: reconstruct full session context (active work, decisions, preferences, facts) at session start.");
  }
  if (availableTools.has("memory_confirm")) {
    lines.push("- **memory_confirm** / **memory_contradict**: boost or demote trust scores for specific memories.");
  }
  lines.push("");
  return lines;
}

// ---------------------------------------------------------------------------
// Plugin registration
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Auto-capture hooks
// ---------------------------------------------------------------------------

function createCaptureHooks(api) {
  // agent_end: capture user prompt and assistant response as observations
  api.on(
    "agent_end",
    async (event) => {
      const config = resolveConfig(api, event?.context);
      if (!config.autoCapture) return;

      const prompt = event?.prompt ?? "";
      const reply = event?.lastMessage?.content ?? event?.reply ?? "";
      const sessionKey = event?.context?.sessionKey ?? "";

      if (!prompt && !reply) return;

      const importance = prompt.length > 80 || reply.length > 200 ? 0.6 : 0.4;

      // Capture user query
      if (prompt) {
        try {
          await saveMemory(config, {
            content: `User asked: ${prompt.slice(0, 2000)}`,
            type: "observation",
            importance: Math.min(importance + 0.05, 1.0),
            tags: ["auto-capture", "user-query"],
          });
        } catch (err) {
          api.logger?.warn?.("[nexus-memory] auto-capture user query failed:", err.message);
        }
      }

      // Capture assistant reply (if non-trivial)
      if (reply && reply.length > 50) {
        try {
          await saveMemory(config, {
            content: `Response: ${reply.slice(0, 2000)}`,
            type: "experience",
            importance,
            tags: ["auto-capture", "assistant-reply"],
          });
        } catch (err) {
          api.logger?.warn?.("[nexus-memory] auto-capture reply failed:", err.message);
        }
      }
    },
    { priority: 10, timeoutMs: 5000 }
  );

  // session_end: save a session summary when the session closes
  api.on(
    "session_end",
    async (event) => {
      const config = resolveConfig(api, event?.context);
      if (!config.autoCapture) return;

      const reason = event?.reason ?? "unknown";
      const sessionKey = event?.context?.sessionKey ?? "unknown";

      try {
        await saveMemory(config, {
          content: `Session ended: ${sessionKey}. Reason: ${reason}.`,
          type: "experience",
          importance: 0.45,
          tags: ["auto-capture", "session-end"],
        });
      } catch (err) {
        api.logger?.warn?.("[nexus-memory] auto-capture session end failed:", err.message);
      }
    },
    { priority: 10, timeoutMs: 5000 }
  );
}

// ---------------------------------------------------------------------------
// Plugin registration
// ---------------------------------------------------------------------------

const plugin = {
  id: PLUGIN_ID,
  name: "Nexus Memory",
  description: "Unified long-term memory via Nexus.",
  kind: "memory",
  register(api) {
    api.registerMemoryCapability?.({ promptBuilder: buildPromptSection });
    api.registerTool(createRecallTool(api));
    api.registerTool(createStoreTool(api));
    api.registerTool(createForgetTool(api));
    api.registerTool(createConsolidateTool(api));
    api.registerTool(createReflectTool(api));
    api.registerTool(createContextTool(api));
    api.registerTool(createConfirmTool(api));
    api.registerTool(createContradictTool(api));
    createCaptureHooks(api);
    api.logger?.info?.("[nexus-memory] Plugin registered (8 tools + auto-capture hooks)");
  }
};

export default plugin;
