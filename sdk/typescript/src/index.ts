/**
 * Nexus SDK — TypeScript client for the Nexus unified AI memory server.
 *
 * Usage:
 *   const nexus = new NexusClient({ secret: process.env.NEXUS_SECRET });
 *   await nexus.save("Auth uses JWT RS256", { importance: 0.9 });
 *   const { results } = await nexus.recall("authentication");
 */

export class NexusError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "NexusError";
  }
}

export interface NexusConfig {
  url?: string;
  secret?: string;
  agentId?: string;
  timeout?: number;
}

export interface SaveOptions {
  agentId?: string;
  memoryType?: "world" | "experience" | "observation" | "preference" | "lesson";
  importance?: number;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface RecallOptions {
  agentId?: string;
  limit?: number;
  memoryTypes?: string[];
  searchModes?: Array<"vector" | "lexical" | "graph" | "temporal">;
}

export interface MemoryResult {
  id: string;
  content: string;
  score: number;
  memory_type: string;
  agent_name?: string;
  importance: number;
  access_count: number;
  created_at?: string;
  matched_by: string[];
}

export class NexusClient {
  private url: string;
  private secret: string;
  private agentId: string;

  constructor(config: NexusConfig = {}) {
    this.url     = (config.url     ?? process.env.NEXUS_URL    ?? "http://100.93.75.87:7777").replace(/\/$/, "");
    this.secret  =  config.secret  ?? process.env.NEXUS_SECRET ?? "";
    this.agentId =  config.agentId ?? "default";
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.secret) h["Authorization"] = `Bearer ${this.secret}`;
    return h;
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const resp = await fetch(`${this.url}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new NexusError(`HTTP ${resp.status}: ${text}`, resp.status);
    }
    return resp.json() as Promise<T>;
  }

  async health(): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.url}/health`, { headers: this.headers() });
    if (!resp.ok) throw new NexusError(`Health check failed: ${resp.status}`, resp.status);
    return resp.json();
  }

  async save(content: string, opts: SaveOptions = {}): Promise<{ id: string; classified_type: string; deduplicated: boolean }> {
    return this.post("/v1/memory/save", {
      content,
      agent_id:    opts.agentId    ?? this.agentId,
      memory_type: opts.memoryType,
      importance:  opts.importance ?? 0.5,
      tags:        opts.tags       ?? [],
      metadata:    opts.metadata   ?? {},
    });
  }

  async recall(query: string, opts: RecallOptions = {}): Promise<{ results: MemoryResult[]; total: number; modes_used: string[] }> {
    return this.post("/v1/memory/recall", {
      query,
      agent_id:     opts.agentId     ?? this.agentId,
      limit:        opts.limit        ?? 10,
      memory_types: opts.memoryTypes  ?? [],
      search_modes: opts.searchModes  ?? ["vector", "lexical", "graph", "temporal"],
    });
  }

  async reflect(query: string, opts: { agentId?: string; depth?: "low" | "mid" | "high"; context?: string } = {}): Promise<string> {
    const r = await this.post<{ reflection: string }>("/v1/memory/reflect", {
      query,
      agent_id: opts.agentId ?? this.agentId,
      depth:    opts.depth   ?? "mid",
      context:  opts.context,
    });
    return r.reflection;
  }

  async context(agentId?: string, tokens = 2000): Promise<Record<string, unknown>> {
    const aid  = agentId ?? this.agentId;
    const resp = await fetch(`${this.url}/v1/agents/${aid}/context?tokens=${tokens}`, { headers: this.headers() });
    if (!resp.ok) throw new NexusError(`HTTP ${resp.status}`, resp.status);
    return resp.json();
  }

  async learn(content: string, agentId?: string, opts: { importance?: number; tags?: string[] } = {}): Promise<Record<string, unknown>> {
    const aid = agentId ?? this.agentId;
    return this.post(`/v1/agents/${aid}/learn`, {
      content,
      importance: opts.importance ?? 0.5,
      tags:       opts.tags       ?? [],
    });
  }

  async saveLesson(content: string, opts: Omit<SaveOptions, "memoryType" | "importance"> = {}): Promise<ReturnType<NexusClient["save"]>> {
    return this.save(content, { ...opts, memoryType: "lesson", importance: 0.9 });
  }

  async saveGlobal(content: string, opts: Omit<SaveOptions, "agentId"> = {}): Promise<ReturnType<NexusClient["save"]>> {
    return this.save(content, { ...opts, agentId: "global" });
  }
}

export default NexusClient;
