import { DEFAULT_AGENT_PREFIX, DEFAULT_NEXUS_URL } from "./constants.js";

export type NexusConfig = {
  nexusUrl: string;
  nexusSecret: string;
  agentIdPrefix: string;
  defaultLimit: number;
};

export type NexusMemory = {
  id?: string;
  content?: string;
  memory_type?: string;
  agent_id?: string;
  importance?: number;
  score?: number;
  tags?: string[];
  metadata?: Record<string, unknown>;
  created_at?: string;
  matched_by?: string[];
};

export type PaperclipMemoryKind =
  | "identity"
  | "project_context"
  | "file_knowledge"
  | "decision"
  | "task_context"
  | "error_pattern"
  | "session_summary"
  | string;

export type RecallInput = {
  query: string;
  agentId?: string;
  companyId?: string;
  limit?: number;
  memoryTypes?: string[];
  includeCompany?: boolean;
};

export type SaveInput = {
  content: string;
  kind?: PaperclipMemoryKind;
  memoryType?: string;
  importance?: number;
  tags?: string[];
  agentId?: string;
  companyId?: string;
  projectId?: string;
  issueId?: string;
  runId?: string;
  source?: Record<string, unknown>;
};

export type ReflectInput = {
  query: string;
  depth?: "shallow" | "mid" | "deep" | string;
  agentId?: string;
  companyId?: string;
};

export function normalizeNexusUrl(value: unknown): string {
  const raw = typeof value === "string" && value.trim() ? value.trim() : DEFAULT_NEXUS_URL;
  return raw.replace(/\/+$/, "");
}

export function toPositiveInt(value: unknown, fallback: number, max: number): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(1, Math.min(max, Math.floor(n)));
}

export function paperclipKindToNexusType(kind: unknown): string {
  switch (kind) {
    case "identity":
    case "project_context":
    case "file_knowledge":
      return "world";
    case "decision":
      return "observation";
    case "task_context":
    case "session_summary":
      return "experience";
    case "error_pattern":
      return "lesson";
    default:
      return "observation";
  }
}

export function normalizeImportance(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return 0.6;
  if (n > 1) return Math.max(0, Math.min(1, n / 10));
  return Math.max(0, Math.min(1, n));
}

export function deriveAgentId(config: Pick<NexusConfig, "agentIdPrefix">, input: { agentId?: string; companyId?: string }): string {
  if (typeof input.agentId === "string" && input.agentId.trim()) return input.agentId.trim();
  const prefix = config.agentIdPrefix || DEFAULT_AGENT_PREFIX;
  if (typeof input.companyId === "string" && input.companyId.trim()) return `${prefix}:company:${input.companyId.trim()}`;
  return prefix;
}

export function formatMemory(memory: NexusMemory): string {
  const type = memory.memory_type ?? "memory";
  const score = typeof memory.score === "number" ? ` score=${memory.score.toFixed(2)}` : "";
  const content = String(memory.content ?? "").replace(/\s+/g, " ").trim();
  return `[${type}${score}] ${content}`.trim();
}

function headers(config: NexusConfig, hasBody: boolean): Record<string, string> {
  const result: Record<string, string> = {};
  if (hasBody) result["content-type"] = "application/json";
  if (config.nexusSecret) result.authorization = `Bearer ${config.nexusSecret}`;
  return result;
}

export async function nexusRequest<T>(config: NexusConfig, path: string, options: { method?: string; body?: unknown; timeoutMs?: number } = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 10000);
  try {
    const response = await fetch(`${config.nexusUrl}${path}`, {
      method: options.method ?? "GET",
      headers: headers(config, options.body !== undefined),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });
    const text = await response.text();
    const data = text.trim() ? JSON.parse(text) : null;
    if (!response.ok) {
      const message = data?.detail ?? data?.error ?? data?.message ?? response.statusText;
      throw new Error(`Nexus ${response.status}: ${message}`);
    }
    return data as T;
  } finally {
    clearTimeout(timeout);
  }
}

export async function nexusHealth(config: NexusConfig): Promise<unknown> {
  return nexusRequest(config, "/health", { timeoutMs: 5000 });
}

export async function nexusRecall(config: NexusConfig, input: RecallInput): Promise<NexusMemory[]> {
  const data = await nexusRequest<{ results?: NexusMemory[] }>(config, "/v1/memory/recall", {
    method: "POST",
    timeoutMs: 15000,
    body: {
      query: input.query.slice(0, 1000),
      agent_id: deriveAgentId(config, input),
      limit: toPositiveInt(input.limit, config.defaultLimit, 50),
      memory_types: Array.isArray(input.memoryTypes) ? input.memoryTypes : [],
      search_modes: ["vector", "lexical", "graph", "temporal"],
      include_company: input.includeCompany === true,
    },
  });
  return Array.isArray(data?.results) ? data.results : [];
}

export async function nexusSave(config: NexusConfig, input: SaveInput): Promise<unknown> {
  const tags = new Set<string>(["paperclip"]);
  if (input.companyId) tags.add(`company:${input.companyId}`);
  if (input.projectId) tags.add(`project:${input.projectId}`);
  if (input.issueId) tags.add(`issue:${input.issueId}`);
  if (input.runId) tags.add(`run:${input.runId}`);
  if (input.kind) tags.add(String(input.kind));
  for (const tag of input.tags ?? []) if (tag) tags.add(String(tag));

  return nexusRequest(config, "/v1/memory/save", {
    method: "POST",
    timeoutMs: 12000,
    body: {
      content: input.content.slice(0, 12000),
      agent_id: deriveAgentId(config, input),
      memory_type: input.memoryType || paperclipKindToNexusType(input.kind),
      importance: normalizeImportance(input.importance),
      tags: [...tags],
      metadata: {
        paperclip: true,
        company_id: input.companyId,
        project_id: input.projectId,
        issue_id: input.issueId,
        run_id: input.runId,
        kind: input.kind,
        source: input.source,
      },
    },
  });
}

export async function nexusReflect(config: NexusConfig, input: ReflectInput): Promise<string> {
  const data = await nexusRequest<{ reflection?: string }>(config, "/v1/memory/reflect", {
    method: "POST",
    timeoutMs: 30000,
    body: {
      query: input.query,
      agent_id: deriveAgentId(config, input),
      depth: input.depth || "mid",
    },
  });
  return data?.reflection ?? "";
}

export type ConsolidateInput = {
  agentId?: string;
  companyId?: string;
  similarity_threshold?: number;
  max_memories?: number;
};

export type ConfirmInput = {
  memoryId: string;
  agentId?: string;
  companyId?: string;
};

export type ContradictInput = {
  memoryId: string;
  reason?: string;
  agentId?: string;
  companyId?: string;
};

export type ContextReconstructInput = {
  query: string;
  agentId?: string;
  companyId?: string;
  limit?: number;
};

export type ConsolidateResult = {
  merged?: number;
  removed?: number;
  clusters?: number;
  details?: unknown;
};

export type ContextGroup = {
  type: string;
  memories: NexusMemory[];
};

export async function nexusConsolidate(config: NexusConfig, input: ConsolidateInput): Promise<ConsolidateResult> {
  return nexusRequest<ConsolidateResult>(config, "/v1/memory/consolidate", {
    method: "POST",
    timeoutMs: 30000,
    body: {
      agent_id: deriveAgentId(config, input),
      similarity_threshold: input.similarity_threshold ?? 0.85,
      max_memories: input.max_memories ?? 500,
    },
  });
}

export async function nexusConfirm(config: NexusConfig, input: ConfirmInput): Promise<unknown> {
  return nexusRequest(config, `/v1/memory/${encodeURIComponent(input.memoryId)}/confirm`, {
    method: "POST",
    timeoutMs: 10000,
    body: {
      agent_id: deriveAgentId(config, input),
    },
  });
}

export async function nexusContradict(config: NexusConfig, input: ContradictInput): Promise<unknown> {
  return nexusRequest(config, `/v1/memory/${encodeURIComponent(input.memoryId)}/contradict`, {
    method: "POST",
    timeoutMs: 10000,
    body: {
      agent_id: deriveAgentId(config, input),
      reason: input.reason ?? "",
    },
  });
}

export async function nexusContextReconstruct(config: NexusConfig, input: ContextReconstructInput): Promise<ContextGroup[]> {
  const data = await nexusRequest<{ results?: NexusMemory[] }>(config, "/v1/memory/recall", {
    method: "POST",
    timeoutMs: 20000,
    body: {
      query: input.query.slice(0, 1000),
      agent_id: deriveAgentId(config, input),
      limit: toPositiveInt(input.limit, config.defaultLimit, 50),
      search_modes: ["vector", "lexical", "graph", "temporal"],
    },
  });
  const results = Array.isArray(data?.results) ? data.results : [];
  const groups = new Map<string, NexusMemory[]>();
  for (const mem of results) {
    const type = mem.memory_type ?? "unknown";
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type)!.push(mem);
  }
  return Array.from(groups.entries()).map(([type, memories]) => ({ type, memories }));
}
