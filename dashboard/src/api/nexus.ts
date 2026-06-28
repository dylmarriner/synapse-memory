// ═══════════════════════════════════════════════════════════════════════════════
// Nexus API client — authenticated fetch wrapper
// ═══════════════════════════════════════════════════════════════════════════════

const TOKEN_KEY = 'nexus_dashboard_token';

function getToken(): string {
  if (typeof window === 'undefined') return '';

  const stored = window.sessionStorage.getItem(TOKEN_KEY);
  if (stored) return stored;

  const token = window.prompt('Enter Nexus dashboard password:')?.trim() ?? '';
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
  return token;
}

export function setToken(token: string) {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken() {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem(TOKEN_KEY);
}

function getErrorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object' && 'detail' in error) return String(error.detail);
  if (error && typeof error === 'object' && 'message' in error) return String(error.message);
  return 'unknown error';
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(options?.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options?.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  const res = await fetch(path, {
    ...options,
    headers,
  });
  if (res.status === 401) {
    clearToken();
    throw new Error('Unauthorized — re-enter your token');
  }
  if (!res.ok) {
    const contentType = res.headers.get('content-type') ?? '';
    const body: unknown = contentType.includes('application/json')
      ? await res.json().catch(() => null)
      : await res.text().catch(() => null);
    throw new Error(`${res.status}: ${getErrorMessage(body).slice(0, 300)}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Stats / Overview ───────────────────────────────────────────────────────

import type {
  StatsResponse,
  MetricsResponse,
  RtkSummary,
  BrowseMemoriesResponse,
  BrowseMemory,
  AgentSummary,
  AgentCard,
  SessionItem,
  RecallDebugResponse,
  MemoryQualityResponse,
  MindDashboardResponse,
  MindThinkResponse,
} from '../types/nexus';

export async function fetchStats(): Promise<StatsResponse> {
  return apiFetch<StatsResponse>('/v1/browse/stats');
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>('/v1/admin/metrics');
}

export async function fetchRtkSummary(): Promise<RtkSummary> {
  return apiFetch<RtkSummary>('/v1/admin/rtk/summary');
}

export async function fetchMemoryQuality(): Promise<MemoryQualityResponse> {
  return apiFetch<MemoryQualityResponse>('/v1/admin/memory-quality');
}

// ── Memories ───────────────────────────────────────────────────────────────

export async function fetchMemories(params: {
  q?: string;
  agent?: string;
  type?: string;
  limit?: number;
  offset?: number;
}): Promise<BrowseMemoriesResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.agent) qs.set('agent', params.agent);
  if (params.type) qs.set('type', params.type);
  qs.set('limit', String(params.limit ?? 20));
  qs.set('offset', String(params.offset ?? 0));
  return apiFetch<BrowseMemoriesResponse>(`/v1/browse/memories?${qs}`);
}

export async function recallMemory(payload: {
  query: string;
  agent_id?: string | null;
  limit?: number;
  memory_types?: string[];
}): Promise<{ results: BrowseMemory[]; total: number; modes_used: string[] }> {
  return apiFetch('/v1/memory/recall', {
    method: 'POST',
    body: JSON.stringify({ ...payload, search_modes: ['vector', 'lexical', 'graph', 'temporal'] }),
  });
}

export async function recallDebug(payload: {
  query: string;
  agent_id?: string | null;
  limit?: number;
}): Promise<RecallDebugResponse> {
  return apiFetch<RecallDebugResponse>('/v1/memory/recall/debug', {
    method: 'POST',
    body: JSON.stringify({ ...payload, search_modes: ['vector', 'lexical', 'graph', 'temporal'] }),
  });
}

export async function deleteMemory(id: string): Promise<void> {
  await apiFetch(`/v1/memory/${id}`, { method: 'DELETE' });
}

export async function confirmMemory(id: string): Promise<void> {
  await apiFetch(`/v1/memory/${id}/confirm`, { method: 'POST' });
}

export async function contradictMemory(id: string): Promise<void> {
  await apiFetch(`/v1/memory/${id}/contradict`, { method: 'POST' });
}

// ── Agents ─────────────────────────────────────────────────────────────────

export async function fetchAgents(): Promise<{ agents: AgentSummary[] }> {
  return apiFetch('/v1/browse/agents');
}

export async function fetchAgentCard(agentId: string): Promise<AgentCard> {
  return apiFetch<AgentCard>(`/v1/agents/${encodeURIComponent(agentId)}/card`);
}

export async function rebuildRepresentation(agentName: string): Promise<{ representation: string | null; rebuilt: boolean }> {
  return apiFetch(`/v1/browse/agents/${encodeURIComponent(agentName)}/represent`, { method: 'POST' });
}

// ── Sessions ───────────────────────────────────────────────────────────────

export async function fetchSessions(limit = 50): Promise<SessionItem[]> {
  return apiFetch<SessionItem[]>(`/v1/sessions?limit=${encodeURIComponent(String(limit))}`);
}

export async function fetchSessionDetail(id: string, limit = 200): Promise<{
  id: string;
  agent_id: string;
  project_key: string | null;
  title: string | null;
  started_at: string;
  ended_at: string | null;
  messages: { id: string; role: string; content: string; token_estimate: number; created_at: string }[];
}> {
  return apiFetch(`/v1/sessions/${encodeURIComponent(id)}?limit=${encodeURIComponent(String(limit))}`);
}

// ── Admin ──────────────────────────────────────────────────────────────────

export async function triggerConsolidate(): Promise<{ success: boolean; stats: Record<string, number> }> {
  return apiFetch('/v1/admin/consolidate', { method: 'POST' });
}

// ── Living Mind ──────────────────────────────────────────────────────────────

export async function fetchMindDashboard(mindId = 'default'): Promise<MindDashboardResponse> {
  return apiFetch<MindDashboardResponse>(`/v1/mind/dashboard?mind_id=${encodeURIComponent(mindId)}`);
}

export async function mindThink(payload: {
  question: string;
  mind_id?: string;
  reasoning_depth?: 'fast' | 'standard' | 'deep';
}): Promise<MindThinkResponse> {
  return apiFetch<MindThinkResponse>('/v1/mind/think', {
    method: 'POST',
    body: JSON.stringify({ mind_id: 'default', reasoning_depth: 'standard', ...payload }),
  });
}
