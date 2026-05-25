/**
 * Synapse SDK — TypeScript client for Synapse Enterprise Memory.
 */

/** Configuration options */
export interface SynapseOptions {
  serverUrl?: string;
  apiKey?: string;
  tenantId?: string;
  defaultProject?: string;
  timeout?: number;
}

/** Memory kind */
export type MemoryKind = "working" | "episodic" | "semantic";

/** Memory result from retrieve/search */
export interface MemoryResult {
  memory_id: string;
  project_key: string;
  kind: MemoryKind;
  content_text: string;
  tags: string[];
  importance: number;
  score?: number;
  version?: number;
  source?: string;
  created_at?: number;
  updated_at?: number;
  last_accessed?: number;
  access_count?: number;
}

/** Generic Synapse API response */
export interface SynapseResponse<T = Record<string, unknown>> {
  ok: boolean;
  error?: string;
  [key: string]: unknown;
}

const DEFAULT_SERVER_URL = "http://100.91.55.113:8765/mcp";

/**
 * Manages MCP sessions with TTL tracking.
 */
class SessionManager {
  private sessionId: string | null = null;
  private expiresAt = 0;

  constructor(private serverUrl: string) {}

  async ensureSession(): Promise<string> {
    const now = Date.now();
    if (this.sessionId && now < this.expiresAt) {
      return this.sessionId;
    }

    const resp = await fetch(this.serverUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-03-26",
          capabilities: {},
          clientInfo: { name: "synapse-sdk-ts", version: "0.1.0" },
        },
      }),
    });

    const sessionId =
      resp.headers.get("mcp-session-id") ?? "";

    if (!sessionId) {
      throw new Error("Synapse server did not return MCP session ID");
    }

    this.sessionId = sessionId;
    this.expiresAt = now + 14 * 60 * 1000; // 14 min
    return sessionId;
  }
}

/**
 * Synapse Memory Client
 */
export class SynapseClient {
  private options: Required<SynapseOptions>;
  private session: SessionManager;

  /** Lifecycle hooks */
  onStore: ((result: SynapseResponse) => void)[] = [];
  onRetrieve: ((result: SynapseResponse) => void)[] = [];

  constructor(options: SynapseOptions = {}) {
    this.options = {
      serverUrl: options.serverUrl ?? DEFAULT_SERVER_URL,
      apiKey: options.apiKey ?? "",
      tenantId: options.tenantId ?? "",
      defaultProject: options.defaultProject ?? "default",
      timeout: options.timeout ?? 30,
    };
    this.session = new SessionManager(this.options.serverUrl);
  }

  /** Register a lifecycle hook */
  on(event: "memory.store" | "memory.retrieve", cb: (...args: unknown[]) => void): this {
    if (event === "memory.store") this.onStore.push(cb as (r: SynapseResponse) => void);
    if (event === "memory.retrieve") this.onRetrieve.push(cb as (r: SynapseResponse) => void);
    return this;
  }

  /** Internal MCP call */
  /** Internal MCP call */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async call(tool: string, args: Record<string, unknown>): Promise<any> {
    const sessionId = await this.session.ensureSession();

    const baseArgs = { ...args };
    if (this.options.apiKey && !baseArgs.api_key) baseArgs.api_key = this.options.apiKey;
    if (this.options.tenantId && !baseArgs.tenant_id) baseArgs.tenant_id = this.options.tenantId;

    const resp = await fetch(this.options.serverUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Mcp-Session-Id": sessionId,
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: tool, arguments: baseArgs },
      }),
    });

    const data = (await resp.json()) as {
      result?: { content?: Array<{ type: string; text: string }>; isError?: boolean };
      error?: { message: string };
    };

    if (data.error) {
      throw new Error(data.error.message);
    }

    const text = data.result?.content?.[0]?.text;
    if (!text) {
      throw new Error("Empty response from Synapse server");
    }

    return JSON.parse(text);
  }

  /** Server health */
  async health(): Promise<SynapseResponse> {
    return this.call("health", {});
  }

  /** Store a memory */
  async store(params: {
    content: string;
    projectKey?: string;
    kind?: MemoryKind;
    tags?: string[];
    importance?: number;
    source?: string;
    ttl?: number;
  }): Promise<SynapseResponse<{ memory_id: string; version: number }>> {
    const result = await this.call("store", {
      project_key: params.projectKey ?? this.options.defaultProject,
      kind: params.kind ?? "episodic",
      content: params.content,
      tags: params.tags ?? [],
      importance: params.importance ?? 0.5,
      source: params.source ?? "synapse-sdk-ts",
      ttl: params.ttl ?? 0,
    });
    this.onStore.forEach((cb) => cb(result));
    return result;
  }

  /** Retrieve memories */
  async retrieve(params: {
    query: string;
    projectKey?: string;
    kinds?: MemoryKind[];
    limit?: number;
    minScore?: number;
  }): Promise<SynapseResponse<{ results: MemoryResult[]; count: number; latency_ms: number }>> {
    const result = await this.call("retrieve", {
      query: params.query,
      project_key: params.projectKey ?? this.options.defaultProject,
      kinds: params.kinds,
      limit: params.limit ?? 10,
      min_score: params.minScore ?? 0,
    });
    this.onRetrieve.forEach((cb) => cb(result));
    return result;
  }

  /** Update a memory */
  async update(params: {
    memoryId: string;
    content: string;
    mergeStrategy?: "merge" | "overwrite" | "append";
    tags?: string[];
  }): Promise<SynapseResponse<{ memory_id: string; version: number }>> {
    return this.call("update", {
      memory_id: params.memoryId,
      content: params.content,
      merge_strategy: params.mergeStrategy ?? "merge",
      tags: params.tags,
    });
  }

  /** Delete a memory */
  async delete(memoryId: string): Promise<SynapseResponse> {
    return this.call("delete", { memory_id: memoryId, source_device: "synapse-sdk-ts" });
  }

  /** Get optimized context pack */
  async context(params: {
    query?: string;
    projectKey?: string;
    limit?: number;
  }): Promise<SynapseResponse<{
    memories: MemoryResult[];
    count: number;
    total_raw_tokens: number;
    total_compressed_tokens: number;
    compression_ratio: number;
    tokens_saved: number;
  }>> {
    return this.call("context", {
      query: params.query ?? "",
      project_key: params.projectKey ?? this.options.defaultProject,
      limit: params.limit ?? 5,
    });
  }

  /** Rank memories */
  async rank(params?: {
    projectKey?: string;
    limit?: number;
  }): Promise<SynapseResponse<{ ranked: Array<Record<string, unknown>>; count: number }>> {
    return this.call("rank", {
      project_key: params?.projectKey ?? this.options.defaultProject,
      limit: params?.limit ?? 20,
    });
  }

  /** Embed texts */
  async embed(texts: string[]): Promise<
    SynapseResponse<{ embeddings: number[][]; dimensions: number; count: number }>
  > {
    return this.call("embed", { texts });
  }

  /** Compress memories */
  async compress(params: {
    memoryIds: string[];
    strategy?: "deduplicate" | "summarize" | "prune_low_value";
    maxTokens?: number;
  }): Promise<SynapseResponse> {
    return this.call("compress", {
      memory_ids: params.memoryIds,
      strategy: params.strategy ?? "deduplicate",
      max_tokens: params.maxTokens ?? 0,
    });
  }

  /** Get single memory */
  async getMemory(memoryId: string): Promise<SynapseResponse<{ memory: MemoryResult }>> {
    return this.call("get_memory", { memory_id: memoryId });
  }

  /** List memories */
  async listMemories(params?: {
    projectKey?: string;
    kind?: string;
    limit?: number;
    offset?: number;
  }): Promise<SynapseResponse> {
    return this.call("list_memories", {
      project_key: params?.projectKey ?? "",
      kind: params?.kind ?? "",
      limit: params?.limit ?? 50,
      offset: params?.offset ?? 0,
    });
  }

  /** Tenant info */
  async getTenantInfo(): Promise<SynapseResponse> {
    return this.call("get_tenant_info", {});
  }
}
