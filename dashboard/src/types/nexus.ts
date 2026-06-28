// ═══════════════════════════════════════════════════════════════════════════════
// Nexus Dashboard — TypeScript interfaces matching the REST API responses
// ═══════════════════════════════════════════════════════════════════════════════

export interface StatsResponse {
  total_memories: number;
  total_agents: number;
  total_entities: number;
  total_conclusions: number;
  by_type: TypeCount[];
}

export interface TypeCount {
  memory_type: string;
  count: number;
}

export interface AgentSummary {
  id: string;
  name: string;
  memory_count: number;
  entity_count: number;
  conclusion_count: number;
  representation: string | null;
  capabilities: string[];
  model: string | null;
  device: string | null;
  hostname: string | null;
  source: string | null;
  last_active: string | null;
  session_count: number;
  last_memory_at: string | null;
  has_summary: boolean;
}

export interface AgentCard {
  agent_id: string;
  display_name: string;
  model: string | null;
  last_active: string | null;
  session_count: number;
  memory_count: number;
  entity_count: number;
  conclusion_count: number;
  summary_count: number;
  confirmed_count: number;
  contradicted_count: number;
  avg_importance: number;
  top_memory_types: Record<string, number>;
  capabilities: string[];
  representation: string | null;
  recent_memories: MemoryResultItem[];
  conclusions: string[];
  source_counts: Record<string, number>;
  confidence: number;
  metadata: Record<string, unknown>;
}

export interface MemoryResultItem {
  id: string;
  content: string;
  score: number;
  memory_type: string;
  agent_id: string | null;
  agent_name: string | null;
  importance: number;
  access_count: number;
  confirmed_count: number;
  contradicted_count: number;
  confidence: number;
  created_at: string | null;
  metadata: Record<string, unknown>;
  matched_by: string[];
}

export interface BrowseMemory {
  id: string;
  content: string;
  memory_type: string;
  agent_name: string | null;
  importance: number;
  access_count: number;
  confirmed_count: number;
  contradicted_count: number;
  created_at: string | null;
  metadata: Record<string, unknown>;
}

export interface BrowseMemoriesResponse {
  memories: BrowseMemory[];
  total: number;
  limit: number;
  offset: number;
}

export interface MetricsResponse {
  healthy: boolean;
  components: Record<string, boolean>;
  totals: Record<string, number>;
  last_24h: Record<string, number>;
  memory_types: Record<string, number>;
  top_agents: { agent_id: string; memories: number; session_count: number; last_active: string | null; last_memory_at: string | null }[];
  rtk: { total_events: number; failed_24h: number; tokens_saved_estimate: number; durable_memories: number };
  recent_events: { id: string; actor: string; action: string; created_at: string | null; detail: unknown }[];
}

export interface RtkSummary {
  total_events: number;
  failures: number;
  tokens_saved_estimate: number;
  avg_duration_ms: number;
  max_duration_ms: number;
  by_agent: { agent_id: string; count: number; tokens_saved_estimate: number; failures: number }[];
  top_failing_commands: { command_label: string; failures: number }[];
  slowest_commands: { command_label: string; count: number; avg_duration_ms: number; max_duration_ms: number }[];
}

export interface SessionItem {
  id: string;
  agent_id: string;
  project_key: string | null;
  title: string | null;
  started_at: string;
  ended_at: string | null;
  message_count: number;
}

export interface RecallDebugResponse {
  query: string;
  expanded_query: string;
  agent_id: string | null;
  modes_requested: string[];
  per_mode: Record<string, MemoryResultItem[]>;
  fused: MemoryResultItem[];
  reranked: MemoryResultItem[];
  fusion: string;
  explanation: Record<string, unknown>;
}

export interface MemoryQualityResponse {
  total_memories: number;
  superseded_count: number;
  expired_count: number;
  avg_confidence: number;
  avg_importance: number;
  total_confirmed: number;
  total_contradicted: number;
  confidence_distribution: Record<string, number>;
  memories_by_type: Record<string, number>;
  top_agents_by_memory_count: { agent: string; count: number }[];
}

// ── Living Mind ──────────────────────────────────────────────────────────────

export interface MindLearnedPattern {
  description: string;
  learned_at: string;
  importance: number;
  evidence_count: number;
  source: string;
}

export interface MindIdentity {
  mind_id: string;
  core_traits: string[];
  learned_patterns: MindLearnedPattern[];
  capabilities: string[];
  limitations: string[];
  relationships: Record<string, MindRelationship>;
}

export interface MindOpinion {
  topic: string;
  stance: 'positive' | 'negative' | 'neutral';
  strength: number;
  rationale: string | null;
  evidence_count: number;
  memory_ids: string[];
  formed_at: string;
  last_updated: string;
}

export interface MindRelationship {
  agent_id: string;
  trust_level: number;
  interaction_count: number;
  shared_projects: string[];
  communication_style: string | null;
  notes?: string | null;
  last_interaction?: string | null;
}

export interface MindDashboardResponse {
  mind_id: string;
  self_description: string;
  identity: MindIdentity;
  opinions: Record<string, MindOpinion>;
  relationships: Record<string, MindRelationship>;
  stats: {
    patterns_learned: number;
    capabilities: number;
    limitations: number;
    opinions_held: number;
    relationships: number;
    active_conversations: number;
  };
  config: Record<string, unknown>;
}

export interface MindProactiveItem {
  type: string;
  content: string;
  relevance: number;
  source_memory_id: string | null;
  created_at?: string;
}

// ── Connections graph ────────────────────────────────────────────────────────

export type ConnNodeType = 'memory' | 'entity' | 'opinion' | 'mind' | 'agent';

export interface ConnNode {
  id: string;
  type: ConnNodeType;
  label: string;
  meta: Record<string, unknown>;
}

export interface ConnEdge {
  from: string;
  to: string;
  kind: 'saved' | 'mentions' | 'relation' | 'evidence' | 'holds' | 'knows';
  label?: string;
}

export interface ConnectionsResponse {
  nodes: ConnNode[];
  edges: ConnEdge[];
  agent_id: string | null;
  mind_id: string;
  counts: Partial<Record<ConnNodeType, number>>;
  node_count: number;
  edge_count: number;
}

// ── Conversations & mind activity ────────────────────────────────────────────

export interface MindConversation {
  id: string;
  agent_id: string;
  started_at: string | null;
  ended_at: string | null;
  turn_count: number;
  open: boolean;
  summary: string | null;
}

export interface MindTurn {
  turn_number: number;
  agent_message: string;
  mind_response: { answer?: string | null; clarifying_question?: string | null; confidence?: number } | null;
  reasoning_trace: {
    intent?: string;
    patterns?: string[];
    insights?: string[];
    conclusion?: string;
    trace?: { name: string; output: string; confidence: number }[];
  } | null;
  confidence: number | null;
  created_at: string | null;
}

export interface MindLearningEvent {
  kind: string;
  description: string;
  source: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

export interface MindProactiveLogItem {
  item_type: string;
  content: string;
  relevance: number;
  used: boolean;
  agent_id: string;
  created_at: string | null;
}

export interface MindThinkResponse {
  answer: string | null;
  clarifying_question: string | null;
  confidence: number;
  memories_cited: unknown[];
  proactive_context: MindProactiveItem[];
  opinions_expressed: MindOpinion[];
  reasoning_trace: {
    intent?: string;
    patterns?: string[];
    insights?: string[];
    conclusion?: string;
    confidence?: number;
    trace?: { name: string; output: string; confidence: number }[];
  } | null;
}
