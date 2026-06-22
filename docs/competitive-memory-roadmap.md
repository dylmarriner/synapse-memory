# Competitive Memory Roadmap

Goal: make Nexus a stronger open, self-hosted agent memory system than
BrainSync, Honcho, Hindsight, and AgentMemory while using RTK to reduce live
command-output tokens.

## Competitor landscape

### BrainSync

Positioning:

- Local IDE intelligence engine for AI coding agents.
- Emphasizes zero-config setup, local SQLite, IDE integration, AST indexing,
  style/rules ingestion, project drift prevention, and privacy.
- Uses MCP for context delivery.

Strengths to match or beat:

- Local-first privacy story.
- IDE awareness and active-project switching.
- AST/codebase structural indexing.
- Rules/style-guide ingestion.
- Very low-friction install.

Nexus response:

- Keep self-hosted Postgres/pgvector for scale, plus optional local deployment.
- Add project-local code intelligence and rules ingestion.
- Add active workspace registry similar to BrainSync's multi-project awareness.
- Keep MCP/REST/OpenAPI compatibility broader than IDE-only workflows.

### Honcho

Positioning:

- Memory infrastructure for stateful agents that understand changing people.
- Strong concepts around workspaces, peers, sessions, messages,
  representations, conclusions, session summaries, and context endpoints.
- Exposes search, chat, context, peer cards, SDKs.

Strengths to match or beat:

- Clean session/peer model.
- Context endpoint for long-running conversations.
- Background derivation pipeline.
- Static low-latency peer representations.

Nexus response:

- Nexus already has agents, conclusions, summaries, and context packs.
- Add first-class sessions/messages so raw conversation history is preserved.
- Add peer cards/profile endpoint with confidence, source links, and recency.
- Add a chat/reflect endpoint that can reason over a peer/profile on demand.

### Hindsight

Positioning:

- Agent memory that learns.
- Has retain/recall/reflect primitives.
- Retain extracts facts, temporal data, entities, and relationships.
- Recall uses four retrieval modes: semantic, keyword/BM25, graph, temporal,
  then reciprocal-rank fusion and cross-encoder reranking.

Strengths to match or beat:

- Clear retain/recall/reflect API.
- Temporal/entity/relationship extraction.
- Cross-encoder reranking.
- Multiple deployment modes and clients.

Nexus response:

- Nexus already has save/recall/reflect and vector/lexical/graph/temporal RRF.
- Add optional reranker layer.
- Add richer temporal normalization and causal/relation extraction.
- Add Hindsight-compatible endpoint aliases: `/retain`, `/recall`, `/reflect`.

### AgentMemory

Positioning:

- Persistent memory for AI coding agents with MCP/CLI/plugin integrations.
- Emphasizes benchmark claims, observability, workers, triggers, queues,
  retries, traces, dashboards, and extensibility.

Strengths to match or beat:

- Strong coding-agent integration packaging.
- Observability and traces for memory operations.
- Worker/plugin architecture.
- Benchmarks/evals.

Nexus response:

- Add memory operation telemetry and evals.
- Add durable event log and retry/dead-letter queues.
- Add dashboard metrics for saves, recalls, hit rate, token cost, and RTK gain.
- Publish benchmark tasks covering preference recall, correction recall,
  stale-memory suppression, project facts, and cross-agent handoff.

## Nexus target architecture

```text
Raw session/event stream
  ↓
Durable raw archive, append-only
  ↓ async workers
Extraction: facts, preferences, lessons, entities, relations, temporal facts
  ↓
Canonical memories + graph + conclusions + summaries + agent/peer cards
  ↓
Recall: vector + lexical + graph + temporal + optional reranker
  ↓
Token-bounded context packs, MCP tools, REST/OpenAPI, SDKs

RTK runs beside this pipeline:
agent shell command → rtk filter → compact output to LLM
```

## Principles

1. **Remember everything durable, inject only what is relevant.**
   Full content remains in storage. Token limits apply only to context packs and
   LLM extraction prompts.

2. **Raw archive first, distillation second.**
   Store raw events/messages before async extraction so nothing important is lost.

3. **Every memory needs provenance.**
   Store source event, session, project, agent, timestamps, extraction method, and
   confidence.

4. **Memory must evolve.**
   Contradictions, supersession, confirmation, decay, access boosts, and temporal
   validity windows are first-class.

5. **Coding agents need codebase memory.**
   Index rules, file summaries, symbols, architectural decisions, and known fixes.

6. **RTK reduces live token noise; Nexus preserves durable knowledge.**

7. **The UI is part of the memory product.**
   Users need to see live learning, source-linked beliefs, recall quality, agent
   profiles, project intelligence, and token/cost savings. See
   `docs/ui-ux-roadmap.md`.

## Implementation phases

### Phase 1 — Raw session/event memory

Add first-class append-only storage:

- `sessions`: agent, project, started_at, ended_at, metadata.
- `messages`: session_id, role, content, created_at, token estimate, metadata.
- `memory_sources`: memory_id → session/message/event provenance.

Endpoints/tools:

- `POST /v1/sessions/start`
- `POST /v1/sessions/{id}/messages`
- `POST /v1/sessions/{id}/end`
- MCP: `session_start`, `session_append`, `session_end_extract`

Why this beats competitors:

- Honcho-style sessions plus Hindsight-style extraction while preserving the raw
  archive for audit/re-extraction.

### Phase 2 — Provenance, confidence, and temporal validity ✓ Implemented

Extend memories with:

- `valid_from`, `valid_until`
- `confidence`
- `source_kind`
- `source_id`
- `extraction_model`
- `extraction_version`

Improve contradiction handling:

- mark old memory as superseded instead of deleting;
- return the newest valid memory by default;
- support historical queries like “what did we believe last month?”.

### Phase 3 — Codebase intelligence like BrainSync ✓ Implemented

Build project-local code memory:

- Index `.cursorrules`, `.windsurfrules`, `.clinerules`, `.agent/rules`,
  `AGENTS.md`, `CLAUDE.md`, `README.md`, architecture docs.
- Summarize files and extract symbols into `file_index`.
- Add active project registry and workspace-focused context.

Endpoints/tools:

- `POST /v1/projects/{key}/index`
- `GET /v1/projects/{key}/rules`
- `GET /v1/projects/{key}/context?query=...`

### Phase 4 — Optional reranking and better recall quality ✓ Implemented

Add a reranker abstraction after RRF:

- Default: current fast RRF.
- Optional local cross-encoder or LLM reranker for top 30 → top N.
- Track recall hit/miss feedback.

Config:

```env
RERANKER_ENABLED=false
RERANKER_PROVIDER=none
RERANK_TOP_K=30
```

### Phase 5 — Peer cards and stateful profiles

Add low-latency, source-linked profile documents:

- identity
- preferences
- working style
- known projects
- strongest lessons
- recent changes
- uncertainty/contradictions

Endpoint/tool:

- `GET /v1/agents/{id}/card`
- MCP: `agent_card`

This matches Honcho representations while adding source/confidence links.

### Phase 6 — Observability and benchmarks like AgentMemory ✓ Implemented

Add metrics:

- saves/day
- recalls/day
- recall modes used
- average results returned
- memories accessed/confirmed/contradicted
- estimated prompt tokens injected
- RTK savings if available via `rtk gain`

Add eval tasks:

- remembers user preference after many sessions
- uses latest preference after contradiction
- recalls exact fix command for recurring bug
- distinguishes global vs agent-specific memory
- retrieves project architecture decision
- avoids injecting irrelevant memories

### Phase 6.5 — Competitive UI

Build the dashboard into a premium agent memory command center:

- overview metrics
- live memory feed
- memory detail/provenance drawers
- agent cards
- project intelligence
- recall lab
- graph explorer
- operations/worker health
- RTK savings panel

See `docs/ui-ux-roadmap.md` for detailed information architecture and phased UI
delivery.

### Phase 7 — Compatibility adapters

Expose aliases/client adapters:

- Hindsight-style: `retain`, `recall`, `reflect`.
- Honcho-style: workspaces, peers, sessions, context, representation.
- BrainSync-style: local project context/rules endpoint.
- AgentMemory-style MCP and coding-agent install scripts.

Initial compatibility aliases are implemented for Hindsight-style
`/v1/retain`, `/v1/recall`, `/v1/reflect`, Honcho-style peer context/card hints,
and AgentMemory-style health discovery.

### Phase 8 — Universal agent/IDE auto-connect

Turn Nexus Doctor into a universal connector for local AI agents, IDEs, desktop
apps, and agent frameworks:

- maintain an expanded target registry for CLI agents, IDEs, editor extensions,
  autonomous SWE agents, and low-code agent builders;
- recursively discover VS Code-compatible `globalStorage` extension configs;
- auto-write MCP configs where supported;
- auto-write instruction files where tools are not supported;
- generate env bootstraps for containerized/local agent runtimes;
- generate OpenAPI import docs/templates for tools like Dify, Flowise, Langflow,
  n8n, OpenWebUI, LibreChat, and AnythingLLM;
- include RTK wrapper guidance so shell-capable agents use `scripts/nexus-rtk`.

High-priority connector targets are tracked in `docs/agent-target-registry.md`.

## Immediate next tasks

1. Create migrations for `sessions`, `messages`, and `memory_sources`. Initial
   migration and startup DDL implemented.
2. Add session REST endpoints and MCP tools. Initial REST endpoints and MCP tools
   implemented.
3. Update hooks to append raw user/assistant/session events. Initial SessionStart,
   UserPromptSubmit, and Stop hook appends implemented.
4. Link extracted memories back to source messages. Initial `memory_sources`
   linking implemented for session extraction.
5. Add `/v1/agents/{id}/card` using existing summaries/conclusions/memories.
   Implemented initial Honcho-style agent card endpoint.
6. Add `/v1/admin/metrics` and RTK gain capture. Initial dashboard metrics
   endpoint implemented; RTK event capture is active via `/v1/rtk/events`.
7. Expand `/v1/rtk/events` into dashboard-visible command telemetry and optional
   hook/proxy integration for agents that support command wrappers. Added RTK
   summary and timeseries admin endpoints for dashboard cards/charts.
8. Expand Nexus Doctor using `docs/agent-target-registry.md`: Gemini CLI, Qwen
   Code, Codex CLI, Goose, Continue, Aider, Roo/Kilo/Kade variants, project
   instruction files, OpenHands/SWE-agent env templates, and OpenAPI templates
   for low-code agent builders.

## RTK role

RTK should be installed and encouraged for every agent shell environment:

```bash
bash scripts/setup-rtk.sh
RTK_INIT_CLAUDE=1 bash scripts/setup-rtk.sh
```

Use RTK for:

- `git status`, `git diff`, `git log`
- `ls`, `tree`, `grep`, `rg`, `read`
- `pytest`, `npm test`, `pnpm test`, `cargo test`, `go test`
- `docker`, `kubectl`, cloud CLIs

Save to Nexus only the durable lessons learned from those commands, not raw noisy
output unless the raw output is itself important evidence.
