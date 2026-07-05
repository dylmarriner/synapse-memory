import {
  definePlugin,
  runWorker,
  type PluginApiRequestInput,
  type PluginApiResponse,
  type PluginContext,
  type ToolResult,
  type ToolRunContext,
} from "@paperclipai/plugin-sdk";
import { API_ROUTES, DEFAULT_AGENT_PREFIX, DEFAULT_NEXUS_URL, TOOL_NAMES } from "./constants.js";
import {
  deriveAgentId,
  formatMemory,
  nexusHealth,
  nexusRecall,
  nexusReflect,
  nexusSave,
  nexusConsolidate,
  nexusConfirm,
  nexusContradict,
  nexusContextReconstruct,
  normalizeNexusUrl,
  toPositiveInt,
  type NexusConfig,
  type RecallInput,
  type ReflectInput,
  type SaveInput,
  type ConsolidateInput,
  type ConfirmInput,
  type ContradictInput,
  type ContextReconstructInput,
} from "./nexus-client.js";

type PluginConfig = {
  nexusUrl?: string;
  nexusSecret?: string;
  nexusSecretRef?: string;
  agentIdPrefix?: string;
  defaultLimit?: number;
};

let currentContext: PluginContext | null = null;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

async function resolveConfig(ctx: PluginContext): Promise<NexusConfig> {
  const raw = await ctx.config.get() as PluginConfig;
  let nexusSecret = typeof raw.nexusSecret === "string" ? raw.nexusSecret : process.env.NEXUS_SECRET ?? "";
  if (typeof raw.nexusSecretRef === "string" && raw.nexusSecretRef.trim()) {
    nexusSecret = await ctx.secrets.resolve(raw.nexusSecretRef.trim());
  }
  return {
    nexusUrl: normalizeNexusUrl(raw.nexusUrl ?? process.env.NEXUS_URL ?? DEFAULT_NEXUS_URL),
    nexusSecret,
    agentIdPrefix: typeof raw.agentIdPrefix === "string" && raw.agentIdPrefix.trim() ? raw.agentIdPrefix.trim() : DEFAULT_AGENT_PREFIX,
    defaultLimit: toPositiveInt(raw.defaultLimit, 8, 50),
  };
}

function toolError(error: unknown): ToolResult {
  return { error: error instanceof Error ? error.message : String(error) };
}

function withRunContext<T extends { agentId?: string; companyId?: string; projectId?: string; runId?: string }>(params: T, runCtx: ToolRunContext): T {
  return {
    ...params,
    companyId: params.companyId ?? runCtx.companyId,
    projectId: params.projectId ?? runCtx.projectId,
    runId: params.runId ?? runCtx.runId,
    agentId: params.agentId ?? runCtx.agentId,
  };
}

async function recordMetric(ctx: PluginContext, name: string, ok: boolean): Promise<void> {
  await ctx.metrics.write(`nexus.${name}`, 1, { status: ok ? "ok" : "error" });
}

async function handleRecall(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as RecallInput, runCtx);
  if (typeof input.query !== "string" || !input.query.trim()) return { error: "query is required" };
  try {
    const config = await resolveConfig(ctx);
    const results = await nexusRecall(config, input);
    await recordMetric(ctx, "recall", true);
    return {
      content: results.length ? results.map(formatMemory).join("\n") : "No Nexus memories found.",
      data: { source: "nexus", agentId: deriveAgentId(config, input), count: results.length, results },
    };
  } catch (error) {
    await recordMetric(ctx, "recall", false);
    return toolError(error);
  }
}

async function handleSave(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as SaveInput, runCtx);
  if (typeof input.content !== "string" || !input.content.trim()) return { error: "content is required" };
  try {
    const config = await resolveConfig(ctx);
    const response = await nexusSave(config, input);
    await recordMetric(ctx, "save", true);
    await ctx.activity.log({
      companyId: input.companyId ?? runCtx.companyId,
      message: "Saved Paperclip memory to Nexus",
      entityType: input.issueId ? "issue" : "agent",
      entityId: input.issueId ?? input.agentId ?? runCtx.agentId,
      metadata: { kind: input.kind, tags: input.tags, nexusAgentId: deriveAgentId(config, input) },
    });
    return { content: "Memory saved to Nexus.", data: { source: "nexus", saved: true, response } };
  } catch (error) {
    await recordMetric(ctx, "save", false);
    return toolError(error);
  }
}

async function handleReflect(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as ReflectInput, runCtx);
  if (typeof input.query !== "string" || !input.query.trim()) return { error: "query is required" };
  try {
    const config = await resolveConfig(ctx);
    const reflection = await nexusReflect(config, input);
    await recordMetric(ctx, "reflect", true);
    return { content: reflection || "No Nexus reflection returned.", data: { source: "nexus", reflection } };
  } catch (error) {
    await recordMetric(ctx, "reflect", false);
    return toolError(error);
  }
}

async function handleConsolidate(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as ConsolidateInput, runCtx);
  try {
    const config = await resolveConfig(ctx);
    const result = await nexusConsolidate(config, input);
    await recordMetric(ctx, "consolidate", true);
    return {
      content: `Consolidation complete: ${result.merged ?? 0} merged, ${result.removed ?? 0} removed, ${result.clusters ?? 0} clusters.`,
      data: { source: "nexus", ...result },
    };
  } catch (error) {
    await recordMetric(ctx, "consolidate", false);
    return toolError(error);
  }
}

async function handleConfirm(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as ConfirmInput, runCtx);
  if (typeof input.memoryId !== "string" || !input.memoryId.trim()) return { error: "memoryId is required" };
  try {
    const config = await resolveConfig(ctx);
    const response = await nexusConfirm(config, input);
    await recordMetric(ctx, "confirm", true);
    return { content: `Memory ${input.memoryId} confirmed.`, data: { source: "nexus", confirmed: true, response } };
  } catch (error) {
    await recordMetric(ctx, "confirm", false);
    return toolError(error);
  }
}

async function handleContradict(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as ContradictInput, runCtx);
  if (typeof input.memoryId !== "string" || !input.memoryId.trim()) return { error: "memoryId is required" };
  try {
    const config = await resolveConfig(ctx);
    const response = await nexusContradict(config, input);
    await recordMetric(ctx, "contradict", true);
    return { content: `Memory ${input.memoryId} contradicted.`, data: { source: "nexus", contradicted: true, response } };
  } catch (error) {
    await recordMetric(ctx, "contradict", false);
    return toolError(error);
  }
}

async function handleContextReconstruct(ctx: PluginContext, params: unknown, runCtx: ToolRunContext): Promise<ToolResult> {
  const input = withRunContext(asRecord(params) as ContextReconstructInput, runCtx);
  if (typeof input.query !== "string" || !input.query.trim()) return { error: "query is required" };
  try {
    const config = await resolveConfig(ctx);
    const groups = await nexusContextReconstruct(config, input);
    await recordMetric(ctx, "context_reconstruct", true);
    const totalMemories = groups.reduce((sum, g) => sum + g.memories.length, 0);
    const lines = groups.map(g => `## ${g.type} (${g.memories.length})\n${g.memories.map(formatMemory).join("\n")}`);
    return {
      content: totalMemories ? lines.join("\n\n") : "No context found.",
      data: { source: "nexus", totalMemories, groupCount: groups.length, groups },
    };
  } catch (error) {
    await recordMetric(ctx, "context_reconstruct", false);
    return toolError(error);
  }
}

async function handleStatus(ctx: PluginContext): Promise<ToolResult> {
  try {
    const config = await resolveConfig(ctx);
    const health = await nexusHealth(config);
    await recordMetric(ctx, "status", true);
    return {
      content: `Nexus reachable at ${config.nexusUrl}`,
      data: { source: "nexus", nexusUrl: config.nexusUrl, agentIdPrefix: config.agentIdPrefix, health },
    };
  } catch (error) {
    await recordMetric(ctx, "status", false);
    return toolError(error);
  }
}

function apiResponse(status: number, body: unknown): PluginApiResponse {
  return { status, body };
}

async function handleApiRequest(ctx: PluginContext, input: PluginApiRequestInput): Promise<PluginApiResponse> {
  try {
    const config = await resolveConfig(ctx);
    const body = asRecord(input.body);
    switch (input.routeKey) {
      case API_ROUTES.health:
        return apiResponse(200, { ok: true, nexusUrl: config.nexusUrl, health: await nexusHealth(config) });
      case API_ROUTES.recall:
        return apiResponse(200, { results: await nexusRecall(config, body as RecallInput) });
      case API_ROUTES.save:
        return apiResponse(200, { saved: true, response: await nexusSave(config, body as SaveInput) });
      case API_ROUTES.reflect:
        return apiResponse(200, { reflection: await nexusReflect(config, body as ReflectInput) });
      case API_ROUTES.consolidate:
        return apiResponse(200, { result: await nexusConsolidate(config, body as ConsolidateInput) });
      case API_ROUTES.confirm:
        return apiResponse(200, { confirmed: true, response: await nexusConfirm(config, body as ConfirmInput) });
      case API_ROUTES.contradict:
        return apiResponse(200, { contradicted: true, response: await nexusContradict(config, body as ContradictInput) });
      case API_ROUTES.context_reconstruct:
        return apiResponse(200, { groups: await nexusContextReconstruct(config, body as ContextReconstructInput) });
      default:
        return apiResponse(404, { error: `Unknown Nexus route: ${input.routeKey}` });
    }
  } catch (error) {
    return apiResponse(502, { error: error instanceof Error ? error.message : String(error) });
  }
}

const plugin = definePlugin({
  async setup(ctx) {
    currentContext = ctx;
    ctx.tools.register(TOOL_NAMES.recall, {
      displayName: "Nexus Recall",
      description: "Search Nexus unified memory for relevant Paperclip context.",
      parametersSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    }, (params, runCtx) => handleRecall(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.save, {
      displayName: "Nexus Save",
      description: "Save durable Paperclip context to Nexus memory.",
      parametersSchema: { type: "object", properties: { content: { type: "string" } }, required: ["content"] },
    }, (params, runCtx) => handleSave(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.reflect, {
      displayName: "Nexus Reflect",
      description: "Synthesize relevant Nexus memory for planning or handoff.",
      parametersSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    }, (params, runCtx) => handleReflect(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.status, {
      displayName: "Nexus Status",
      description: "Check Nexus health from Paperclip.",
      parametersSchema: { type: "object", properties: {} },
    }, () => handleStatus(ctx));
    ctx.tools.register(TOOL_NAMES.consolidate, {
      displayName: "Nexus Consolidate",
      description: "Merge duplicate Nexus memories to improve recall quality.",
      parametersSchema: { type: "object", properties: { similarity_threshold: { type: "number" }, max_memories: { type: "number" } } },
    }, (params, runCtx) => handleConsolidate(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.confirm, {
      displayName: "Nexus Confirm",
      description: "Confirm a Nexus memory as accurate, boosting its trust score.",
      parametersSchema: { type: "object", properties: { memoryId: { type: "string" } }, required: ["memoryId"] },
    }, (params, runCtx) => handleConfirm(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.contradict, {
      displayName: "Nexus Contradict",
      description: "Flag a Nexus memory as incorrect or outdated.",
      parametersSchema: { type: "object", properties: { memoryId: { type: "string" }, reason: { type: "string" } }, required: ["memoryId"] },
    }, (params, runCtx) => handleContradict(ctx, params, runCtx));
    ctx.tools.register(TOOL_NAMES.context_reconstruct, {
      displayName: "Nexus Context Reconstruct",
      description: "Reconstruct cross-session context from Nexus, grouped by memory type.",
      parametersSchema: { type: "object", properties: { query: { type: "string" }, limit: { type: "number" } }, required: ["query"] },
    }, (params, runCtx) => handleContextReconstruct(ctx, params, runCtx));
    ctx.logger.info("Nexus Memory plugin ready");
  },
  async onHealth() {
    if (!currentContext) return { status: "error", message: "Plugin context not initialized" };
    const result = await handleStatus(currentContext);
    return result.error ? { status: "error", message: result.error } : { status: "ok", message: result.content, diagnostics: result.data };
  },
  async onValidateConfig(config) {
    const nexusUrl = normalizeNexusUrl(config.nexusUrl);
    try {
      new URL(nexusUrl);
      return { ok: true, warnings: [`Nexus URL configured: ${nexusUrl}`] };
    } catch {
      return { ok: false, errors: ["nexusUrl must be a valid URL"] };
    }
  },
  async onApiRequest(input) {
    if (!currentContext) return apiResponse(503, { error: "Plugin context not initialized" });
    return handleApiRequest(currentContext, input);
  },
});

export default plugin;
runWorker(plugin, import.meta.url);
