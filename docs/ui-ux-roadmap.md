# Nexus UI/UX Roadmap

Goal: give Nexus a polished, confidence-inspiring interface comparable to or
better than BrainSync, Honcho, Hindsight, and AgentMemory while making its deeper
memory architecture visible and useful.

## Product direction

Nexus should not look like a database browser. It should look like an agent
memory command center:

- live memory feed
- agent intelligence cards
- project/codebase intelligence
- recall quality visualization
- graph exploration
- session timeline
- contradictions and trust management
- RTK token savings and cost avoidance
- observability for memory operations

The UI should answer three questions instantly:

1. **What does Nexus know?**
2. **Why does it believe that?**
3. **How much context/cost did it save me?**

## Competitor UI strengths to match

### BrainSync-style strengths

- Polished landing/dashboard visuals.
- IDE-native feeling.
- Live feed of memory/code intelligence.
- Project hotspot/anomaly cards.
- Strong privacy/local-state messaging.
- “Agent just knows” product narrative.

Nexus UI response:

- Project intelligence page with indexed rules, architecture docs, files,
  symbols, and recent project memories.
- Live sync/activity feed.
- Local/self-hosted privacy indicators.
- Codebase intelligence cards: rules loaded, files indexed, known conventions,
  recurring fixes.

### Honcho-style strengths

- Clean conceptual surfaces around peers/users/sessions.
- Context endpoint and representation outputs are easy to understand.
- Peer cards and session summaries are productized concepts.

Nexus UI response:

- Agent Cards page.
- Session timeline page.
- Context-pack preview: shows exactly what would be injected into an agent.
- Source-linked conclusions and profile facts.

### Hindsight-style strengths

- Clear retain/recall/reflect primitives.
- Memory learning pipeline is understandable.
- Recall is positioned as multi-strategy and high quality.

Nexus UI response:

- Recall lab page showing vector/lexical/graph/temporal results before and after
  fusion.
- Reflection workbench.
- Extraction pipeline view: raw event → extracted memory → entities/relations →
  conclusion.

### AgentMemory-style strengths

- Observability, traces, workers, queues, metrics.
- Coding-agent installation emphasis.
- Benchmark/eval confidence.

Nexus UI response:

- Operations page: worker health, Redis queue depth, failed jobs, consolidation
  runs, extraction stats.
- Eval/benchmark page.
- RTK savings widget and command categories.
- Install wizard for Claude/Cline/Windsurf/Cursor/OpenCode/Paperclip/OpenClaw.

## Recommended information architecture

```text
Dashboard
├─ Overview
│  ├─ Memory totals
│  ├─ Active agents
│  ├─ Recall activity
│  ├─ RTK savings
│  └─ System health
├─ Live Feed
│  ├─ new memories
│  ├─ extractions
│  ├─ contradictions
│  ├─ recalls
│  └─ agent handoffs
├─ Memories
│  ├─ search/filter/list
│  ├─ detail drawer
│  ├─ provenance
│  ├─ trust controls
│  └─ edit/supersede/delete
├─ Agents
│  ├─ agent cards
│  ├─ profile/representation
│  ├─ preferences/lessons
│  ├─ context preview
│  └─ handoff notes
├─ Sessions
│  ├─ session list
│  ├─ message timeline
│  ├─ extracted facts
│  └─ replay/re-extract
├─ Projects
│  ├─ active workspace
│  ├─ rules/style guides
│  ├─ files/symbols
│  ├─ architecture decisions
│  └─ recurring fixes
├─ Recall Lab
│  ├─ query input
│  ├─ mode-by-mode results
│  ├─ fused ranking
│  ├─ optional reranker comparison
│  └─ feedback buttons
├─ Graph
│  ├─ entities
│  ├─ relations
│  ├─ impacted files/blast radius
│  └─ temporal links
├─ Operations
│  ├─ Postgres/Redis/worker health
│  ├─ queue depth
│  ├─ extraction failures
│  ├─ consolidation reports
│  └─ memory operation traces
└─ Integrations
   ├─ MCP configs
   ├─ IDE setup wizard
   ├─ RTK setup
   ├─ SDK snippets
   └─ plugin status
```

## Visual style

Recommended style: premium technical dark UI, not generic admin panel.

Design language:

- deep navy/black background
- glassy cards with subtle borders
- cyan/violet/emerald accents
- small animated activity indicators
- dense but readable information hierarchy
- monospace only for IDs/logs/code; Inter/Geist-style sans for UI
- clear trust signals: confirmed, contradicted, superseded, stale, global

Key components:

- metric cards
- memory cards
- agent cards
- session timeline
- live event feed
- split-pane detail drawer
- graph canvas
- recall result comparison columns
- health badges
- setup checklist cards

## Screens in detail

### 1. Overview dashboard

Widgets:

- Total memories
- Agents online/recent
- Entities/relations
- Conclusions/lessons
- Recalls in last 24h
- Extraction queue depth
- Worker health
- Estimated prompt tokens injected
- RTK estimated tokens saved

Hero panel:

```text
Nexus Memory Mesh
4-mode recall · source-linked memory · RTK-optimized command context
```

### 2. Live Feed

Use existing SSE endpoint `/v1/stream`.

Event types:

- `memory.created`
- `memory.extracted`
- `memory.contradicted`
- `memory.confirmed`
- `agent.context_loaded`
- `session.ended`
- `consolidation.completed`
- `rtk.savings_updated`

Current backend only broadcasts basic `memory` events. Expand over time.

### 3. Memories

Current API support:

- `GET /v1/browse/memories`
- `DELETE /v1/browse/memories/{id}`
- `POST /v1/memory/{memory_id}/confirm`
- `POST /v1/memory/{memory_id}/contradict`

Needed additions:

- memory detail endpoint
- provenance/source endpoint
- edit/supersede endpoint
- batch actions
- confidence/validity display after provenance migration

### 4. Agent Cards

Current API support:

- `GET /v1/browse/agents`
- `GET /v1/agents/{id}/context`
- `POST /v1/browse/agents/{agent_name}/represent`

Needed addition:

- `GET /v1/agents/{id}/card`

Card sections:

- profile summary
- strongest preferences
- strongest lessons
- known projects
- recent memories
- contradictions/uncertainties
- source links

### 5. Project Intelligence

Current schema has `projects`, `file_index`, and `events` compatibility tables.

Needed UI:

- project list
- indexed files
- symbols
- rules loaded
- recent project events
- recurring fixes
- architectural decisions

Needed API:

- `GET /v1/projects`
- `GET /v1/projects/{key}/files`
- `GET /v1/projects/{key}/rules`
- `GET /v1/projects/{key}/events`

### 6. Recall Lab

This is the most important “prove it works” UI.

Flow:

1. Enter query.
2. Run vector/lexical/graph/temporal separately.
3. Show each result list side by side.
4. Show fused ranking.
5. Show why each result ranked: mode matches, score, importance, trust,
   recency, confirmed/contradicted counts.
6. Buttons: useful, not useful, confirm, contradict, pin.

Needed API enhancement:

- `POST /v1/memory/recall/debug`

Response should include per-mode candidates and fusion explanation.

### 7. Graph Explorer

Show:

- entity nodes
- relation edges
- memories connected to entities
- temporal clusters
- blast radius for files/projects

Initial implementation can use plain SVG or canvas. Later use Cytoscape.js or
Sigma.js if adding a frontend build pipeline.

### 8. Operations

Show:

- health checks
- worker heartbeat
- Redis queue depth
- extraction jobs processed
- failed jobs
- consolidation stats
- DB index status
- RTK installation/savings

Needed API:

- `GET /v1/admin/metrics`
- `GET /v1/admin/queues`
- `GET /v1/admin/rtk`

## Frontend implementation options

### Option A — Keep zero-build HTML first

Pros:

- simplest deployment
- no Node dependency
- works inside current FastAPI app

Cons:

- harder to build complex graph/observability UI

Good for immediate polish.

### Option B — Add React/Vite SPA

Pros:

- much easier to build competitor-grade UI
- component library, routing, charts, graph explorer

Cons:

- adds build pipeline

Recommended if the goal is to genuinely compete visually.

Suggested stack:

- Vite + React + TypeScript
- Tailwind CSS
- shadcn/ui or custom Radix components
- TanStack Query
- Recharts for metrics
- Cytoscape.js/Sigma.js for graph

### Option C — FastAPI templates + HTMX

Pros:

- minimal JS
- nice server-driven UI

Cons:

- graph/recall lab less ergonomic

## Phased UI delivery

### UI Phase 1 — Premium zero-build dashboard refresh

- Replace existing dashboard landing with polished overview.
- Add stat cards using `/v1/browse/stats`.
- Add memory feed using `/v1/browse/memories` + `/v1/stream`.
- Add agent cards using `/v1/browse/agents`.
- Add RTK setup/status panel with instructions.

Implemented: zero-build dashboard now includes an Operations tab backed by
`/v1/admin/metrics` and `/v1/admin/rtk/summary`, showing sessions, messages,
RTK token savings, failures, per-agent RTK usage, and recent events.

### UI Phase 2 — Agent and memory detail drawers

- Memory detail drawer.
- Confirm/contradict/delete actions.
- Agent context preview.
- Rebuild representation button.

Implemented: selecting an agent in the zero-build dashboard now loads
`/v1/agents/{id}/card` and displays confidence, representation, source counts,
memory type distribution, conclusions, and top memories.

### UI Phase 3 — Recall Lab

- Add debug recall endpoint.
- Build mode-by-mode comparison UI.
- Add feedback controls.

Implemented: `/v1/memory/recall/debug` returns vector, lexical, graph,
temporal, fused, and reranked results with explanation metadata. The zero-build
dashboard includes a Recall Lab tab for side-by-side mode comparison. Recall Lab
result cards include Useful/Not useful feedback controls that call confirm and
contradict memory trust endpoints.

### UI Phase 4 — Sessions and provenance

- Requires backend Phase 1 session tables.
- Session timeline.
- Raw message archive.
- Extracted-memory provenance links.

Implemented: zero-build dashboard now includes a Sessions tab that lists recent
raw sessions and displays selected session metadata plus raw message timeline.

### UI Phase 5 — Graph and project intelligence

- Entity graph.
- Project rules/files/events.
- Architecture decision cards.
- Codebase hotspot cards.

### UI Phase 6 — Full React/Vite app

- Move from zero-build HTML to SPA if needed.
- Add routing, graph canvas, charts, persistent filters, keyboard shortcuts.

## Immediate quick wins

1. Create a new `/ui` or dashboard page with:
   - Overview
   - Live feed
   - Memories
   - Agents
   - Integrations/RTK

2. Add backend metrics endpoint:
   - memory counts over time
   - recent saves
   - recent recalls if recall logging is added
   - worker heartbeat
   - Redis queue length

3. Add `agent_card` endpoint.

4. Add `recall/debug` endpoint.

5. Add screenshots/GIFs to README once the UI exists.

## Success criteria

Nexus UI should make users say:

- “I can see exactly what my agents know.”
- “I can trust this because every memory has source and confidence.”
- “I can debug recall quality instead of guessing.”
- “I can watch memory evolve live.”
- “This feels like an intelligence layer, not just a CRUD app.”
