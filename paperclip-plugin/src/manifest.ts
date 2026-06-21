import type { PaperclipPluginManifestV1 } from "@paperclipai/plugin-sdk";
import { API_ROUTES, PLUGIN_ID, PLUGIN_VERSION, TOOL_NAMES } from "./constants.js";

const manifest: PaperclipPluginManifestV1 = {
  id: PLUGIN_ID,
  apiVersion: 1,
  version: PLUGIN_VERSION,
  displayName: "Nexus Memory",
  description: "Connects Paperclip-managed agents to Nexus unified long-term memory for recall, save, reflection, and status checks.",
  author: "Nexus",
  categories: ["connector", "automation"],
  capabilities: [
    "agent.tools.register",
    "api.routes.register",
    "http.outbound",
    "metrics.write",
    "activity.log.write",
  ],
  entrypoints: {
    worker: "./dist/src/worker.js",
  },
  instanceConfigSchema: {
    type: "object",
    properties: {
      nexusUrl: {
        type: "string",
        title: "Nexus URL",
        default: "http://100.93.75.87:7777",
        description: "Base URL for the Nexus memory server.",
      },
      nexusSecret: {
        type: "string",
        title: "Nexus API Secret",
        description: "Bearer token for Nexus. Prefer configuring this as a Paperclip secret ref if your install supports secret references.",
      },
      nexusSecretRef: {
        type: "string",
        title: "Nexus Secret Reference",
        description: "Optional Paperclip secret ref. If set, it is resolved at call time and overrides nexusSecret.",
      },
      agentIdPrefix: {
        type: "string",
        title: "Agent ID Prefix",
        default: "paperclip",
        description: "Prefix used when deriving Nexus agent_id from Paperclip company/agent context.",
      },
      defaultLimit: {
        type: "number",
        title: "Default Recall Limit",
        default: 8,
      },
    },
  },
  tools: [
    {
      name: TOOL_NAMES.recall,
      displayName: "Nexus Recall",
      description: "Search Nexus unified memory using vector, lexical, graph, and temporal recall. Use before answering questions about prior work, decisions, preferences, lessons, projects, or issues.",
      parametersSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          memoryTypes: { type: "array", items: { type: "string" } },
          agentId: { type: "string" },
          includeCompany: { type: "boolean" },
        },
        required: ["query"],
      },
    },
    {
      name: TOOL_NAMES.save,
      displayName: "Nexus Save",
      description: "Save durable Paperclip context, lessons, preferences, decisions, issue knowledge, or run summaries to Nexus.",
      parametersSchema: {
        type: "object",
        properties: {
          content: { type: "string" },
          kind: { type: "string" },
          memoryType: { type: "string" },
          importance: { type: "number" },
          tags: { type: "array", items: { type: "string" } },
          agentId: { type: "string" },
        },
        required: ["content"],
      },
    },
    {
      name: TOOL_NAMES.reflect,
      displayName: "Nexus Reflect",
      description: "Ask Nexus to synthesize relevant memory into a structured reflection for planning, debugging, or handoff.",
      parametersSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          depth: { type: "string", enum: ["shallow", "mid", "deep"] },
          agentId: { type: "string" },
        },
        required: ["query"],
      },
    },
    {
      name: TOOL_NAMES.status,
      displayName: "Nexus Status",
      description: "Check Nexus health and current Paperclip-to-Nexus configuration.",
      parametersSchema: {
        type: "object",
        properties: {},
      },
    },
    {
      name: TOOL_NAMES.consolidate,
      displayName: "Nexus Consolidate",
      description: "Merge duplicate and near-duplicate Nexus memories to reduce clutter and improve recall quality.",
      parametersSchema: {
        type: "object",
        properties: {
          similarity_threshold: { type: "number", description: "Similarity threshold for merging (0-1, default 0.85)." },
          max_memories: { type: "number", description: "Maximum memories to scan (default 500)." },
          agentId: { type: "string" },
        },
      },
    },
    {
      name: TOOL_NAMES.confirm,
      displayName: "Nexus Confirm",
      description: "Confirm a Nexus memory as accurate, boosting its trust score for future recall.",
      parametersSchema: {
        type: "object",
        properties: {
          memoryId: { type: "string", description: "The ID of the memory to confirm." },
          agentId: { type: "string" },
        },
        required: ["memoryId"],
      },
    },
    {
      name: TOOL_NAMES.contradict,
      displayName: "Nexus Contradict",
      description: "Flag a Nexus memory as incorrect or outdated, lowering its trust score.",
      parametersSchema: {
        type: "object",
        properties: {
          memoryId: { type: "string", description: "The ID of the memory to contradict." },
          reason: { type: "string", description: "Why this memory is incorrect or outdated." },
          agentId: { type: "string" },
        },
        required: ["memoryId"],
      },
    },
    {
      name: TOOL_NAMES.context_reconstruct,
      displayName: "Nexus Context Reconstruct",
      description: "Reconstruct cross-session context by recalling memories across all search modes and grouping by type.",
      parametersSchema: {
        type: "object",
        properties: {
          query: { type: "string" },
          limit: { type: "number" },
          agentId: { type: "string" },
        },
        required: ["query"],
      },
    },
  ],
  apiRoutes: [
    {
      routeKey: API_ROUTES.health,
      method: "GET",
      path: "/health",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "query", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.recall,
      method: "POST",
      path: "/recall",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.save,
      method: "POST",
      path: "/save",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.reflect,
      method: "POST",
      path: "/reflect",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.consolidate,
      method: "POST",
      path: "/consolidate",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.confirm,
      method: "POST",
      path: "/confirm",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.contradict,
      method: "POST",
      path: "/contradict",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
    {
      routeKey: API_ROUTES.context_reconstruct,
      method: "POST",
      path: "/context-reconstruct",
      auth: "board-or-agent",
      capability: "api.routes.register",
      companyResolution: { from: "body", key: "companyId" },
    },
  ],
};

export default manifest;
