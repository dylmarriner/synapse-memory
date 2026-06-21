/**
 * Nexus Adapter for Paperclip Memory Plugin
 * Replaces Paperclip's internal DB calls with Nexus API calls.
 * Maps Paperclip MemoryKind system to Nexus memory types.
 */

import { request as httpsRequest } from "node:https";
import { request as httpRequest } from "node:http";

// ── Config ────────────────────────────────────────────────────────────────

const NEXUS_URL = process.env.NEXUS_URL || "http://100.93.75.87:7777";
const NEXUS_SECRET = process.env.NEXUS_SECRET || "...";

// Paperclip MemoryKind → Nexus memory type mapping
function kindToNexusType(kind: string): string {
  const mapping: Record<string, string> = {
    "identity": "world",
    "project_context": "world",
    "file_knowledge": "world",
    "decision": "observation",
    "task_context": "experience",
    "error_pattern": "lesson",
    "session_summary": "experience",
    "user_preference": "preference",
    "agent_observation": "observation",
  };
  return mapping[kind] || "observation";
}

// Nexus memory type → Paperclip MemoryKind mapping (for recall)
function nexusToPaperclipType(nexusType: string): string {
  const mapping: Record<string, string> = {
    "world": "identity",
    "observation": "agent_observation",
    "preference": "user_preference",
    "lesson": "error_pattern",
    "experience": "task_context",
  };
  return mapping[nexusType] || "agent_observation";
}

// ── HTTP helpers ──────────────────────────────────────────────────────────

function nexusPost<T>(path: string, body: any, timeoutMs = 8000): Promise<T> {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const url = new URL(NEXUS_URL + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${NEXUS_SECRET}`,
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
  return new Promise((resolve, reject) => {
    const url = new URL(NEXUS_URL + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "GET",
      headers: { "Authorization": `Bearer ${NEXUS_SECRET}` },
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

// ── Paperclip adapter functions ─────────────────────────────────────────────

export async function storeMemory(ctx: any, input: {
  content: string;
  kind: string;
  agentId: string;
  importance?: number;
  tags?: string[];
  companyId?: string;
}): Promise<{ id: string }> {
  /**
   * Replace Paperclip's internal DB writes with Nexus API calls.
   * Maps Paperclip MemoryKind to Nexus memory types.
   */
  const nexusType = kindToNexusType(input.kind);
  const tags = [input.kind, ...(input.tags || [])];
  
  // Add company context to metadata
  const metadata: any = { paperclip: true };
  if (input.companyId) {
    metadata.company_id = input.companyId;
  }
  
  const response = await nexusPost("/v1/memory/save", {
    content: input.content,
    agent_id: input.agentId,
    memory_type: nexusType,
    importance: (input.importance || 5) / 10,  // normalize 1-10 → 0-1
    tags: tags,
    metadata: metadata,
  });
  
  return { id: response.id };
}

export async function recall(ctx: any, input: {
  query?: string;
  kind?: string;
  agentId: string;
  limit?: number;
}): Promise<any[]> {
  /**
   * Replace Paperclip's internal DB queries with Nexus API calls.
   * Supports both query-based and kind-based recall.
   */
  const query = input.query || input.kind || "";
  const limit = input.limit || 10;
  
  // Map Paperclip kind to Nexus memory types for filtering
  const memoryTypes = input.kind ? [kindToNexusType(input.kind)] : undefined;
  
  const response = await nexusPost("/v1/memory/recall", {
    query: query.slice(0, 500),
    agent_id: input.agentId,
    limit: limit,
    memory_types: memoryTypes,
    search_modes: ["vector", "lexical"],  // Fast path for recall
  });
  
  // Convert Nexus format back to Paperclip format
  return (response.results || []).map((nexusMem: any) => ({
    id: nexusMem.id,
    content: nexusMem.content,
    kind: nexusToPaperclipType(nexusMem.memory_type),
    importance: Math.round((nexusMem.importance || 0.5) * 10),  // normalize 0-1 → 1-10
    tags: nexusMem.metadata?.tags || [],
    createdAt: nexusMem.created_at,
  }));
}

export async function decayMemories(ctx: any, input: {
  agentId: string;
  olderThanDays?: number;
}): Promise<{ decayed: number }> {
  /**
   * Trigger Nexus consolidation for memory decay.
   * Nexus handles decay automatically via scheduled consolidation.
   */
  try {
    await nexusPost("/admin/consolidate", {});
    return { decayed: 1 };  // Consolidation was triggered
  } catch (error) {
    console.error("Failed to trigger Nexus consolidation:", error);
    return { decayed: 0 };
  }
}

export async function getAgentIdentity(ctx: any, input: {
  agentId: string;
}): Promise<{ identity: string | null }> {
  /**
   * Retrieve agent identity from Nexus.
   * This syncs Paperclip agent identities with Nexus.
   */
  try {
    const response = await nexusGet(`/v1/memory/profile/${input.agentId}`);
    
    // Look for identity memories in the profile
    const identityMemories = response.memories
      .filter((m: any) => m.memory_type === "world" && 
                         (m.metadata?.tags?.includes("identity") || 
                          m.content.toLowerCase().includes("identity")))
      .slice(0, 3);  // Take top 3 identity memories
    
    if (identityMemories.length > 0) {
      const identity = identityMemories
        .map((m: any) => m.content)
        .join("\n");
      return { identity };
    }
    
    return { identity: null };
  } catch (error) {
    console.error("Failed to get agent identity from Nexus:", error);
    return { identity: null };
  }
}

export async function syncAgentIdentity(ctx: any, input: {
  agentId: string;
  identity: string;
}): Promise<{ success: boolean }> {
  /**
   * Sync Paperclip agent identity to Nexus.
   * Ensures all agents have consistent identity across platforms.
   */
  try {
    await nexusPost("/v1/memory/save", {
      content: `Agent identity: ${input.identity}`,
      agent_id: input.agentId,
      memory_type: "world",
      importance: 0.95,
      tags: ["identity", "system-prompt"],
      metadata: { paperclip: true, identity_sync: true },
    });
    
    // Also save to global for cross-platform visibility
    await nexusPost("/v1/memory/save", {
      content: `${input.agentId} agent identity: ${input.identity}`,
      agent_id: "global",
      memory_type: "world",
      importance: 0.9,
      tags: ["agent-identity", input.agentId],
      metadata: { paperclip: true, source_agent: input.agentId },
    });
    
    return { success: true };
  } catch (error) {
    console.error("Failed to sync agent identity to Nexus:", error);
    return { success: false };
  }
}

export async function updateAgentActivity(ctx: any, input: {
  agentId: string;
  model?: string;
  capabilities?: string[];
}): Promise<{ success: boolean }> {
  /**
   * Update agent activity in Nexus registry.
   * Helps with agent discovery and multi-agent coordination.
   */
  try {
    const body: any = {};
    if (input.model) body.model = input.model;
    if (input.capabilities) body.capabilities = input.capabilities;
    
    await nexusPost(`/v1/agents/${input.agentId}/update`, body);
    return { success: true };
  } catch (error) {
    console.error("Failed to update agent activity in Nexus:", error);
    return { success: false };
  }
}

// ── Health check ───────────────────────────────────────────────────────────

export async function healthCheck(): Promise<{ healthy: boolean; nexusUrl: string }> {
  try {
    const response = await nexusGet("/health");
    return { 
      healthy: response.healthy || false, 
      nexusUrl: NEXUS_URL 
    };
  } catch (error) {
    return { healthy: false, nexusUrl: NEXUS_URL };
  }
}