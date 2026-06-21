# Nexus Optimization & Enhancement Plan
# Generated: 2026-06-16
# Status: Ready to execute

---

## PHASE 1 — COST REDUCTION (Immediate savings, no architectural changes)

### 1.1 Batch Extraction (70% LLM cost reduction)
**File:** `app/memory/extract.py`

Current: 3 separate LLM calls per memory (classify + entities + conclusion)
Target: 1 LLM call per memory, all 3 tasks in one prompt

```python
_BATCH_PROMPT = """Analyze this memory and return a JSON object:
{
  "type": "world|experience|observation|preference|lesson",
  "entities": [{"name": "...", "type": "person|place|org|concept|tech|project|other"}],
  "conclusion": "1-sentence conclusion (omit if not observation/lesson)"
}

Memory: {content}
Return ONLY valid JSON."""
```

### 1.2 Low-Importance Skipping (60% of extraction skipped)
**File:** `app/memory/extract.py` → `_process_job()`

If memory importance < 0.4 AND type is NOT lesson:
  → Classify only (no entities, no conclusions, no patterns)
  → Saves 2 LLM calls per low-value memory

### 1.3 Lazy Summary Rebuild
**File:** `app/memory/extract.py` → `_build_summary()`

Current: Rebuilds every 20 jobs per agent
Target: Only rebuild when agent starts a new session (via /v1/agents/{id}/context endpoint)

### 1.4 Embedding Cache
**File:** `app/memory/ingest.py` + `app/embeddings.py`

Cache embeddings in Redis with 24h TTL.
Key: `embed:{md5(text[:200])}`
Skip embedding call if cached hit.

### 1.5 Smarter Recall — 2-Phase
**File:** `app/routers/memory.py` → `recall()`

Current: All 4 modes always run in parallel
Target: Run vector + lexical first. If results >= limit, skip graph + temporal.
          Only run all 4 if results < limit/2.

---

## PHASE 2 — AGENT PERFORMANCE (Better recall, better context)

### 2.1 Dedup on Save
**File:** `app/memory/ingest.py` → `save_memory()`

Before saving, check if semantically similar memory exists (cosine > 0.92).
If yes: bump importance + access_count instead of creating duplicate.

### 2.2 Priority-Based Context Assembly
**File:** `app/agents/context.py` → `get_context()`

Order memories by: lesson > preference > observation > world > experience
Within same type: by importance DESC, then recency DESC
This ensures lessons (corrections) are always in context.

### 2.3 Cross-Agent Memory Sharing
**File:** `new feature`

When saving to 'global', auto-inject a summary of global memories into ALL agent contexts.
Agents automatically know cross-agent facts without explicit recall.

### 2.4 Smart Importance Auto-Scaling
**File:** `app/memory/consolidate.py`

Boost importance of memories that match CURRENT conversation context.
If a memory is recalled AND the user continues discussing that topic within N turns:
  → additional importance boost (like drilling down on an active topic)

### 2.5 Conclusion-to-Prompt Injection
**File:** `app/agents/context.py`

Conclusions should be injected as explicit "rules" in system prompt format:
  "REMEMBER: User prefers dark mode"
  "REMEMBER: Deploy to production on Tuesdays only"
This makes conclusions more actionable than raw memory content.

---

## PHASE 3 — AGENT-TO-AGENT COMMUNICATION

### 3.1 Agent Note Delivery
**File:** `app/agents/context.py`

When building context for an agent:
1. Check for unread notes (memory with tag "agent-note" for this agent)
2. Inject them as "📬 Unread message from {source_agent}: ..."
3. Mark as read after injection (delete or tag "read")

### 3.2 Skill/Knowledge Transfer
**File:** `new API endpoint`

POST /v1/agents/{from}/transfer/{to}
  → Takes recent high-importance memories from agent A
  → Saves them as memories for agent B with tag "transferred"
  → Both agents now share that knowledge

### 3.3 Agent Registry
**File:** `app/routers/browse.py`

Add agent metadata fields: capabilities, model, last_active, session_count
Agents can discover each other's capabilities via API.
Useful for multi-agent architectures.

---

## PHASE 4 — ARCHITECTURE & RELIABILITY

### 4.1 Vector Index (Performance at Scale)
**File:** `database migration`

Add pgvector HNSW index:
```sql
CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
```
Without this, vector search is O(n) full table scan. HNSW makes it O(log n).
Critical once memories exceed 10,000.

### 4.2 Worker Health Check Fix
**File:** `docker-compose.yml` + `app/memory/extract.py`

The BLPOP timeout error is harmless but marks worker as unhealthy.
Fix: wrap blpop in a try/except that returns None on timeout instead of raising.
Add a proper health endpoint to worker.

### 4.3 Memory Versioning
**File:** `app/models/schema.py` + `app/routers/memory.py`

Add `version` and `superseded_by` fields to Memory table.
When a memory is updated, increment version, link old version.
Essential for tracking how user preferences evolve over time.

### 4.4 Batch Save Endpoint
**File:** `app/routers/memory.py`

POST /v1/memory/batch — accepts array of MemorySaveRequest
Saves all in one transaction. Queues ONE extraction job for the batch.
Reduces DB overhead when an agent saves 10 memories at once.

### 4.5 Memory Export/Backup
**File:** `app/routers/admin.py`

GET /v1/admin/export/{agent_id} → returns JSONL of all memories
GET /v1/admin/export/all → full backup
POST /v1/admin/import → restore from backup

### 4.6 Scheduled Consolidation Reports
**File:** `app/worker.py`

Daily at 3am: run full consolidation, send summary report with stats
Helps identify memory growth patterns and spot issues early.

---

## PHASE 5 — TOKEN OPTIMIZATION (Agent-side)

### 5.1 Hermes Plugin — Smarter Context Injection
**File:** Hermes plugin `__init__.py`

Current: Injects summary + conclusions + up to 8 memories
Optimized: Inject only summary + 3 most important conclusions. 
            Recall is available on-demand via tool call.
            Saves 400-800 tokens per turn.

### 5.2 Hermes Plugin — Conditional Save
**File:** Hermes plugin `__init__.py` → `sync_turn()`

Current: saves every turn if user_content > 20 chars
Optimized: only save if content contains new information
  (check for keywords: "I like", "I prefer", "I use", "remember that", "note:", "important")
  Saves 70% of saves that have no informational value.

### 5.3 OpenClaw Extension — Same optimizations
**File:** OpenClaw extension `index.ts`

Apply same conditional save + slim context injection patterns.

---

## EXECUTION ORDER

Phase 1 first — immediate cost savings (can do in one session)
Phase 2 next — makes agents smarter right away
Phase 3 after — enables multi-agent workflows
Phase 4 ongoing — reliability at scale
Phase 5 last — agent-side tweaks

---

## KEY METRICS TO TRACK

Before any changes:
- LLM calls per save: 3 (classify + entities + conclusion)
- LLM calls per 20 jobs: 60 + 1 pattern + 1 summary = 62
- Embedding calls per save: 1
- Summary rebuilds: every 20 jobs (~5min at 1 job/15s)
- Agent context tokens: ~1500 avg

After Phase 1:
- LLM calls per save: 1 (batched)
- LLM calls per 20 jobs: 20 + 0 pattern + 1 summary = 21 (66% reduction)
- Embedding calls: variable (cached)
- Summary rebuilds: only on session start (95%+ reduction)


## PHASE 6 — PAPERCLIP INTEGRATION

### Overview
Paperclip (`/media/kubuntux/DEVELOPMENT1/paperclip/`) is a control plane for AI-agent companies.
It already has a `plugin-agent-memory` plugin with full memory infrastructure (store, recall, decay, indexing, shared state).
Goal: Make Paperclip-managed agents use Nexus as their memory backend instead of Paperclip's internal DB.

### 6.1 Nexus Adapter for Paperclip Memory Plugin
**Files:** `packages/plugins/plugin-agent-memory/src/memory/store.ts`, `recall.ts`, `decay.ts`

Replace Paperclip's internal DB calls with Nexus API calls.
The existing `MemoryKind` system maps directly to Nexus memory types:
  - `identity` → Nexus `world` + tag `identity`
  - `project_context` → Nexus `world` + tag `project_context`
  - `file_knowledge` → Nexus `world` + tag `file_knowledge`
  - `decision` → Nexus `observation` + tag `decision`
  - `task_context` → Nexus `experience` + tag `task_context`
  - `error_pattern` → Nexus `lesson` + tag `error_pattern`
  - `session_summary` → Nexus `experience` + tag `session_summary`

```typescript
// nexus-adapter.ts — pluggable memory backend
import { request } from "node:https";

const NEXUS_URL = process.env.NEXUS_URL || "http://100.93.75.87:7777";
const NEXUS_SECRET = process.env.NEXUS_SECRET || "...";

async function nexusPost(path: string, body: any) {
  // POST to Nexus API with auth
}

// Replace storeMemory() internal DB writes with:
export async function storeMemory(ctx, input) {
  const nexusType = kindToNexusType(input.kind);
  await nexusPost("/v1/memory/save", {
    content: input.content,
    agent_id: input.agentId,
    memory_type: nexusType,
    importance: (input.importance || 5) / 10,  // normalize 1-10 → 0-1
    tags: [input.kind, ...(input.tags || [])],
    metadata: { paperclip: true, company_id: input.companyId }
  });
}

// Replace recall() internal DB queries with:
export async function recall(ctx, query) {
  const results = await nexusPost("/v1/memory/recall", {
    query: query.query || query.kind || "",
    agent_id: query.agentId,
    limit: query.limit || 10,
    memory_types: [kindToNexusType(query.kind)]
  });
  return results.results.map(nexusToPaperclipFormat);
}
```

### 6.2 Configuration
**File:** `packages/plugins/plugin-agent-memory/src/config/schema.ts`

```typescript
nexusUrl: z.string().optional().describe("Nexus server URL (default: http://100.93.75.87:7777)"),
nexusSecret: z.string().optional().describe("Nexus API secret"),
nexusEnabled: z.boolean().optional().describe("Use Nexus as memory backend (default: false)"),
```

### 6.3 Paperclip Agent Identity Sync
When a Paperclip agent starts a session:
  1. Check Nexus for existing agent identity (`agent_id = paperclip:{agentId}`)
  2. If found, inject into Paperclip's system prompt
  3. Sync Paperclip session summaries back to Nexus

### 6.4 Cross-Platform Memory Sharing
With Nexus as the backend:
  - Hermes agent and Paperclip agent can share memories via `agent_id: "global"`
  - A memory saved by Paperclip CEO agent is visible to Hermes
  - All agents use the same entity graph (entities extracted by Nexus apply universally)

### 6.5 Paperclip Plugin Manifest Update
**File:** `packages/plugins/plugin-agent-memory/src/manifest.ts`

```typescript
instanceConfigSchema: instanceConfigSchema.extend({
  nexusUrl: z.string().optional(),
  nexusSecret: z.string().optional(),
  nexusEnabled: z.boolean().optional(),
}),
```

---

## EXECUTION ORDER (Updated)

1. Phase 1 — Cost Reduction (batch extraction, low-importance skip, lazy summary)
2. Phase 6 — Paperclip Nexus Adapter (connect Paperclip agents to Nexus)
3. Phase 2 — Agent Performance (dedup, priority context, cross-agent sharing)
4. Phase 5 — Token Optimization (Hermes + OpenClaw agent-side)
5. Phase 3 — Agent-to-Agent (notes, transfer, registry)
6. Phase 4 — Architecture (vector index, worker fix, versioning, export)

