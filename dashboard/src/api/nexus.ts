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
  ConnectionsResponse,
  MindConversation,
  MindTurn,
  MindLearningEvent,
  MindProactiveLogItem,
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

export async function fetchMindIdentity(mindId = 'default'): Promise<import('../types/nexus').MindIdentity> {
  return apiFetch(`/v1/mind/identity/${encodeURIComponent(mindId)}`);
}

export async function fetchMindOpinions(mindId = 'default'): Promise<{ opinions: import('../types/nexus').MindOpinion[] }> {
  return apiFetch(`/v1/mind/opinions/${encodeURIComponent(mindId)}`);
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

// ── Connections graph ────────────────────────────────────────────────────────

export async function fetchConnections(params?: { agentId?: string; limit?: number }): Promise<ConnectionsResponse> {
  const qs = new URLSearchParams();
  if (params?.agentId) qs.set('agent_id', params.agentId);
  qs.set('limit', String(params?.limit ?? 120));
  return apiFetch<ConnectionsResponse>(`/v1/graph/connections?${qs}`);
}

// ── Conversations & mind activity ────────────────────────────────────────────

export async function fetchMindConversations(mindId = 'default', limit = 50): Promise<{ conversations: MindConversation[] }> {
  return apiFetch(`/v1/mind/conversations?mind_id=${encodeURIComponent(mindId)}&limit=${limit}`);
}

export async function fetchMindConversationTurns(conversationId: string): Promise<{ turns: MindTurn[] }> {
  return apiFetch(`/v1/mind/conversations/${encodeURIComponent(conversationId)}/turns`);
}

export async function fetchMindLearningEvents(mindId = 'default', limit = 100): Promise<{ events: MindLearningEvent[] }> {
  return apiFetch(`/v1/mind/learning-events?mind_id=${encodeURIComponent(mindId)}&limit=${limit}`);
}

export async function fetchMindProactiveLog(mindId = 'default', limit = 100): Promise<{ items: MindProactiveLogItem[] }> {
  return apiFetch(`/v1/mind/proactive-log?mind_id=${encodeURIComponent(mindId)}&limit=${limit}`);
}

// ── Code-context (Iris Gate Ladder) ──────────────────────────────────────

export interface CodeStats {
  repo_id: string;
  files: number;
  symbols: number;
  edges: number;
  languages: number;
  wiki_articles: number;
  iris_usage: Record<number, number>;
  recent_runs: { id: string; files_indexed: number; symbols: number; edges: number; duration_ms: number; finished_at: string | null }[];
}

export interface SymbolCard {
  id: string;
  name: string;
  qualified_name: string;
  kind: string;
  location: { path: string; start_line: number; end_line: number };
  language: string;
  signature: string;
  docstring: string;
  return_type: string;
  parameters: { name: string }[];
  decorators: string[];
  visibility: string;
  is_exported: boolean;
  is_async: boolean;
  complexity: number;
  line_count: number;
  source_snippet?: string;
}

export interface CodeRepo {
  id: string;
  name: string;
  root_path: string;
  agent_id: string | null;
  last_indexed_at: string | null;
  created_at: string | null;
}

export interface WikiArticle {
  title: string;
  slug: string;
  section: string;
  tokens: number;
}

export async function fetchCodeStats(): Promise<CodeStats> {
  return apiFetch<CodeStats>('/v1/code/stats');
}

export async function fetchCodeRepos(): Promise<{ repos: CodeRepo[] }> {
  return apiFetch<{ repos: CodeRepo[] }>('/v1/code/repos');
}

export async function indexCodeRepo(name: string, rootPath: string): Promise<{ repo_id: string; files_indexed: number; symbols: number; edges: number; duration_ms: number }> {
  return apiFetch('/v1/code/repos', {
    method: 'POST',
    body: JSON.stringify({ name, root_path: rootPath, max_files: 5000 }),
  });
}

export async function searchCodeSymbols(q: string, kind?: string, limit = 20): Promise<{ symbols: { id: string; name: string; qualified_name: string; kind: string; path: string; start_line: number; end_line: number; signature: string; docstring: string }[]; count: number }> {
  const params = new URLSearchParams();
  params.set('q', q);
  params.set('limit', String(limit));
  if (kind) params.set('kind', kind);
  return apiFetch(`/v1/code/search?${params}`);
}

export async function getCodeSymbolCard(qualifiedName: string, includeSource = false): Promise<SymbolCard> {
  const params = new URLSearchParams();
  if (includeSource) params.set('include_source', 'true');
  return apiFetch<SymbolCard>(`/v1/code/symbol/${encodeURIComponent(qualifiedName)}?${params}`);
}

export interface IrisResult {
  rung: number;
  card?: SymbolCard;
  bytes?: number;
  est_tokens?: number;
  error?: string;
}

export async function irisGate(symbol: string, rung: number, justification?: string): Promise<IrisResult> {
  return apiFetch<IrisResult>('/v1/code/iris', {
    method: 'POST',
    body: JSON.stringify({ symbol, rung, ...(justification ? { justification } : {}) }),
  });
}

export interface BlastResult {
  target: string;
  depth: number;
  total_affected: number;
  by_depth: Record<number, number>;
  symbols: { depth: number; symbol: { name: string; qualified_name: string; kind: string } }[];
}

export async function blastRadius(target: string, depth = 2): Promise<BlastResult> {
  return apiFetch<BlastResult>('/v1/code/blast', {
    method: 'POST',
    body: JSON.stringify({ target, depth }),
  });
}

export async function getFileOutline(path: string): Promise<{ file: string; language: string; bytes: number; line_count: number; symbols: { name: string; qualified_name: string; kind: string; start_line: number; end_line: number; signature: string }[] }> {
  return apiFetch(`/v1/code/file/outline?path=${encodeURIComponent(path)}`);
}

export async function generateWiki(): Promise<{ sections: Record<string, string>; stats: { files: number; symbols: number; edges: number; languages: number } }> {
  return apiFetch('/v1/code/wiki/generate', { method: 'POST' });
}

export async function fetchWikiIndex(): Promise<{ articles: WikiArticle[]; count: number }> {
  return apiFetch<{ articles: WikiArticle[]; count: number }>('/v1/code/wiki');
}

export async function fetchWikiArticle(slug: string): Promise<{ title: string; slug: string; content: string; section: string; token_estimate: number }> {
  return apiFetch(`/v1/code/wiki/${encodeURIComponent(slug)}`);
}
