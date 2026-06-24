# Nexus Domination Plan — 12-Item Battle Plan

**Effort level:** medium — balanced approach with standard implementation and testing

## Goal
Implement all features needed to dominate BrainSync, AgentMemory, Hindsight, Honcho, Mem0, Zep/Graphiti, Letta, LangMem, Cognee, and EverOS across architecture, benchmarks, DX, and observability.

---

## Sprint 1 — P0: Correctness & Competitive Benchmarking (Days 1–3)

### 1. LongMemEval-S Benchmark Adapter
**Why:** No published score = invisible in comparisons. AgentMemory 95.2%, Hindsight 94.6%, EverOS 93%. Must publish.

**Files:**
- `scripts/nexus-eval` — add `--eval-format longmemeval-s` flag and `--input FILE` flag
- New function `run_longmemeval(input_file, nexus_url, api_key)` after line 244

**Implementation:**
```
scripts/nexus-eval:
  - Add CLI args: --eval-format (nexus|longmemeval-s), --input (path to JSON file)
  - New function run_longmemeval_s(input_file, url, key):
      Load JSON: [{question, answer, conversation_history[]}]
      For each sample:
        1. Ingest conversation_history messages via POST /v1/memory/retain
        2. Query POST /v1/memory/recall with question
        3. Score: exact match OR llm-judge compare results[0].content vs answer
        4. Clean up memories (unless --no-cleanup)
      Output: {"total": N, "correct": N, "accuracy": float, "samples": [...]}
  - Output format matches LongMemEval-S schema for publishable results
```

### 2. Coding-Specific Eval Tasks (expand nexus-eval)
**Files:** `scripts/nexus-eval` — add 4 more tasks after line 234

Tasks to add:
- `symbol-recall` — store 20 function signatures, recall "what does parse_config return?"
- `bug-fix-chain` — store multi-step debug session, retrieve root cause
- `cross-file-ref` — store architecture facts across 3 files, recall dependencies
- `agent-scope-bleed` — 3 agents share project, verify correct scoping

---

## Sprint 2 — P1: Recall Quality (Days 3–6)

### 3. Local Cross-Encoder Reranker
**Why:** LLM reranker is expensive (1 API call per recall); cross-encoder is 10–50ms locally.

**Files:**
- `requirements.txt` — add `sentence-transformers>=3.0`
- `app/config.py` — add `reranker_local_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"`, `reranker_batch_size: int = 16`
- `app/search/rerank.py` — add `_local_rerank()` function and wire into `rerank()` at line 56

**Implementation:**
```python
# app/search/rerank.py — add after _llm_rerank():

_cross_encoder: CrossEncoder | None = None

def _get_cross_encoder(model_name: str) -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder(model_name)
    return _cross_encoder

async def _local_rerank(query, results, limit, top_k):
    model = _get_cross_encoder(settings.reranker_local_model)
    pairs = [(query, r.content) for r in results[:top_k]]
    scores = await asyncio.get_event_loop().run_in_executor(
        None, model.predict, pairs
    )
    ranked = sorted(zip(scores, results[:top_k]), key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked[:limit]]

# In rerank() dispatch at line 56:
elif provider == "local":
    return await _local_rerank(query, results, limit, top_k)
```

**.env.example:** Add `RERANKER_PROVIDER=local`, `RERANKER_LOCAL_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2`

### 4. Memory Confidence Decay Worker
**Why:** Confidence is stored on memories but never decremented. Stale facts stay at 1.0 forever.

**Files:**
- `app/memory/consolidate.py` — add Pass 6 after line 133
- `app/config.py` — add `confidence_decay_rate: float = 0.95`, `confidence_decay_interval_days: int = 7`, `confidence_floor: float = 0.1`

**Implementation:**
```python
# app/memory/consolidate.py — add after pass 5:

async def _decay_confidence(db: AsyncSession) -> int:
    """Pass 6: Weekly confidence decay for aging memories."""
    result = await db.execute(text("""
        UPDATE memories
        SET confidence = GREATEST(:floor, confidence * :rate)
        WHERE created_at < NOW() - INTERVAL '1 day' * :interval_days
          AND superseded_by IS NULL
          AND confidence > :floor
    """), {
        "floor": settings.confidence_floor,
        "rate": settings.confidence_decay_rate,
        "interval_days": settings.confidence_decay_interval_days,
    })
    await db.commit()
    return result.rowcount
```

Call `_decay_confidence` from `consolidate()` and include count in consolidation report.

### 5. Bi-Temporal Graph Edges
**Why:** Relations need time-slicing for "who worked on X between dates" queries.

**Files:**
- `app/main.py` — add 2 ALTER TABLE migrations in `_run_migrations()`
- `app/models/schema.py` — add `valid_from` and `valid_until` to `Relation` ORM
- `app/search/graph.py` — add temporal filter to WHERE clause

**Migration SQL to add in `_run_migrations()`:**
```sql
ALTER TABLE relations ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE relations ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_relations_valid_from ON relations(valid_from);
```

**Schema change (`app/models/schema.py` after line 82):**
```python
valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

**Graph search filter (`app/search/graph.py` line 47 WHERE clause):**
```sql
AND (r.valid_until IS NULL OR r.valid_until > NOW())
AND r.valid_from <= NOW()
```

---

## Sprint 3 — P1: Observability & Privacy (Days 6–9)

### 6. OpenTelemetry Instrumentation
**Why:** No spans = blind in production. Competitors like Letta and Zep ship OTEL traces.

**Files:**
- `requirements.txt` — add 5 otel packages
- `app/main.py` — initialize tracer provider at startup
- `app/memory/extract.py` — wrap consolidate/extract calls in spans
- `app/routers/memory.py` — span around recall pipeline
- `app/config.py` — add `otel_enabled: bool = False`, `otel_endpoint: str = ""`

**requirements.txt additions:**
```
opentelemetry-sdk>=1.25
opentelemetry-api>=1.25
opentelemetry-instrumentation-fastapi>=0.46b0
opentelemetry-instrumentation-sqlalchemy>=0.46b0
opentelemetry-instrumentation-redis>=0.46b0
```

**app/main.py — add after imports (conditional on otel_enabled):**
```python
if settings.otel_enabled:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
```

**Key spans to add:**
- `nexus.recall` in memory router (tags: agent_id, modes, result_count, reranker)
- `nexus.extract` in extract worker (tags: memory_count, entity_count)
- `nexus.consolidate` in consolidate.py (tags: decayed, deduplicated)

### 7. Privacy / Consent / Deletion Framework
**Why:** GDPR compliance and enterprise sales require export + forget.

**Files:**
- `app/routers/agents.py` — add 2 new endpoints
- `app/config.py` — add `allow_agent_export: bool = True`, `allow_agent_forget: bool = True`

**New endpoints in `app/routers/agents.py`:**

```python
@router.get("/{agent_id}/export")
async def export_agent_data(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Export all data for an agent as JSON (GDPR Article 20 compliant)."""
    agent = await get_or_create(db, agent_id)
    memories = await db.execute(select(Memory).where(Memory.agent_id == agent.id))
    entities = await db.execute(select(Entity).where(Entity.agent_id == agent.id))
    sessions = await db.execute(select(Session).where(Session.agent_id == agent.id))
    return {
        "agent": {"id": str(agent.id), "name": agent.name},
        "memories": [m.__dict__ for m in memories.scalars()],
        "entities": [e.__dict__ for e in entities.scalars()],
        "sessions": [s.__dict__ for s in sessions.scalars()],
        "exported_at": datetime.utcnow().isoformat(),
    }

@router.post("/{agent_id}/forget")
async def forget_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Permanently delete all data for an agent (GDPR Article 17 compliant)."""
    agent = await get_or_create(db, agent_id)
    # Cascade delete (FK constraints handle children)
    mem_count = (await db.execute(delete(Memory).where(Memory.agent_id == agent.id))).rowcount
    ent_count = (await db.execute(delete(Entity).where(Entity.agent_id == agent.id))).rowcount
    await db.execute(delete(Agent).where(Agent.id == agent.id))
    await db.commit()
    return {"deleted_memories": mem_count, "deleted_entities": ent_count, "agent": agent_id}
```

Also add MCP tool entries for `export_agent` and `forget_agent` in `app/mcp.py`.

---

## Sprint 4 — P2: Infrastructure & DX (Days 9–13)

### 8. Agent Identity Resolution / Peer Merge
**Why:** Agents that rename themselves fragment memory. No way to merge Claude-3.5 vs Claude-3.7 histories.

**Files:**
- `app/routers/agents.py` — add `POST /v1/agents/resolve`
- `app/agents/peer.py` — add `merge_agents()` helper

**New endpoint:**
```python
@router.post("/resolve")
async def resolve_agents(
    body: AgentResolveRequest,  # {primary: str, duplicates: list[str]}
    db: AsyncSession = Depends(get_db)
):
    """Merge duplicate agent memories into primary agent."""
    primary = await get_or_create(db, body.primary)
    dup_ids = []
    for name in body.duplicates:
        dup = await get_or_create(db, name)
        dup_ids.append(dup.id)
    
    # Reassign all memories, entities, sessions to primary
    await db.execute(update(Memory).where(Memory.agent_id.in_(dup_ids)).values(agent_id=primary.id))
    await db.execute(update(Entity).where(Entity.agent_id.in_(dup_ids)).values(agent_id=primary.id))
    await db.execute(update(Session).where(Session.agent_id.in_(dup_ids)).values(agent_id=primary.id))
    await db.execute(delete(Agent).where(Agent.id.in_(dup_ids)))
    await db.commit()
    return {"merged_into": body.primary, "removed_agents": body.duplicates}
```

Add `AgentResolveRequest` Pydantic model to `app/models/api.py`.

### 9. Zero-Friction Embedded Install Mode
**Why:** Every competitor has `pip install X && X start`. Nexus requires Docker + Postgres + Redis = days of setup friction.

**Files:**
- `requirements.txt` — add `fakeredis>=2.20`, `aiosqlite>=0.20` as optional (extras)
- `app/config.py` — add `embedded_mode: bool = False`
- `app/db.py` — support `sqlite+aiosqlite:///nexus.db` when embedded
- `app/memory/extract.py` — use `fakeredis` when embedded
- New file: `nexus/cli.py` — click-based CLI entrypoint
- `setup.py` or `pyproject.toml` — add `console_scripts: nexus = nexus.cli:main`

**cli.py skeleton:**
```python
import click, uvicorn, asyncio

@click.group()
def main(): pass

@main.command()
@click.option("--port", default=7777)
@click.option("--embedded/--full", default=True)
def start(port, embedded):
    """Start Nexus memory server."""
    import os
    if embedded:
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///nexus.db")
        os.environ.setdefault("REDIS_URL", "fakeredis://")
        os.environ.setdefault("EMBEDDED_MODE", "true")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
```

**db.py changes:**
```python
# If DATABASE_URL starts with sqlite, use aiosqlite driver
# Skip pgvector extension creation
# Use JSON column instead of pgvector for embeddings (cosine via Python)
```

### 10. Tree-Sitter AST Indexing
**Why:** Regex symbol extraction misses nested classes, methods, decorators, line numbers.

**Files:**
- `requirements.txt` — add `tree-sitter>=0.23`, `tree-sitter-python>=0.23`, `tree-sitter-javascript>=0.23`, `tree-sitter-go>=0.23`
- `app/routers/synapse.py` — replace `_extract_symbols()` at lines 49–53 with AST-based extractor
- `app/models/schema.py` — update `file_index.symbols` JSONB to store `{name, type, line, scope}`

**New `_extract_symbols()` in `app/routers/synapse.py`:**
```python
def _extract_symbols(content: str, language: str) -> list[dict]:
    try:
        import tree_sitter_python, tree_sitter_javascript
        from tree_sitter import Language, Parser
        LANGS = {
            "python": Language(tree_sitter_python.language()),
            "javascript": Language(tree_sitter_javascript.language()),
        }
        parser = Parser(LANGS.get(language, LANGS["python"]))
        tree = parser.parse(content.encode())
        symbols = []
        _walk_ast(tree.root_node, symbols, scope="")
        return symbols[:500]
    except ImportError:
        return _extract_symbols_regex(content)  # fallback
```

Keep `_extract_symbols_regex` as fallback so tree-sitter is optional.

---

## Sprint 5 — P2: Dashboard & Memory Quality (Days 13–16)

### 11. Memory Quality Dashboard Endpoint
**Why:** No visibility into memory health, decay rates, confidence distribution, or contradiction rate.

**Files:**
- `app/routers/admin.py` (already exists per git log) — add `GET /v1/admin/memory-quality`
- `app/main.py` — wire into router

**Endpoint returns:**
```json
{
  "total_memories": 15420,
  "avg_confidence": 0.82,
  "confidence_distribution": {"0.0-0.2": 120, "0.2-0.4": 340, ...},
  "avg_importance": 0.61,
  "superseded_count": 892,
  "expired_count": 203,
  "memories_by_type": {"preference": 3400, "fact": 8200, ...},
  "recent_decay_pass": {"decayed": 1200, "avg_new_confidence": 0.78, "ran_at": "..."},
  "top_agents_by_memory_count": [{"agent": "claude", "count": 4200}, ...]
}
```

Query uses indexed columns only — no full scans.

Also add a **Memory Quality** tab in the dashboard HTML (`app/main.py` around line 402) with visual confidence distribution bar chart (using inline SVG or Chart.js from CDN).

### 12. Agent Federation / Multi-Node P2P Sync
**Why:** Single-node only — Mem0 Cloud and Zep Cloud offer multi-instance sync. Needed for enterprise.

**Files:**
- `app/config.py` — add `federation_peers: list[str] = []`, `federation_secret: str = ""`
- New file: `app/federation.py` — peer sync logic
- `app/main.py` — register federation router and startup task
- `app/routers/federation.py` — new router

**Minimal P2P protocol:**
```
POST /v1/federation/push  — receive memory batch from peer
GET  /v1/federation/pull  — serve memories updated since ?since=ISO8601
POST /v1/federation/hello — peer discovery handshake
```

**Sync algorithm:**
- On memory write, queue to `nexus:federation` Redis stream
- Background task polls stream every 30s, pushes to configured peers
- Conflict resolution: last-writer-wins by `updated_at`, trust multiplier from peer metadata
- Auth: HMAC-SHA256 signature on payload using `FEDERATION_SECRET`

This is intentionally a minimal first cut — just enough to demo multi-node capability.

---

## Sprint 6 — Doc Audit Gaps (Days 16–19)

Gaps discovered during doc audit of `docs/` — items documented as planned but not yet implemented.

### 13. Project Intelligence API (ui-ux-roadmap.md Phase 5)
**Why:** UI roadmap specifies these endpoints for the Graph/Project Intelligence tab but they don't exist.

**Files:**
- `app/routers/synapse.py` — add 3 new GET endpoints

**Endpoints to add:**
```python
GET /v1/synapse/projects
  # Lists all projects: [{key, name, description, file_count, created_at}]

GET /v1/synapse/projects/{key}/files
  # Returns file_index entries for project: [{path, language, symbols[], updated_at}]

GET /v1/synapse/projects/{key}/events
  # Returns events scoped to project from events table: [{event_type, content, created_at}]
  # Filter: WHERE metadata->>'project' = :key OR project_id = :project_id
```

These unblock the dashboard's Project Intelligence and Graph Explorer tabs.

### 14. Nexus Doctor — 6 Pending Agent Integrations (agent-target-registry.md items 10–16)
**Why:** Registry backlog has 6 confirmed-pending targets that exist on this machine or are high-value enough to add now.

**Files:**
- `scripts/nexus-doctor` — add handler cases for each target
- `integrations/doctor/targets.json` — add entries

**Targets to implement:**

| Target | Integration | Path/Format |
|--------|-------------|-------------|
| OpenHands | env bootstrap | `~/.openhands/nexus.env` |
| SWE-agent | env bootstrap | `~/.sweagent/nexus.env` |
| Continue.dev | MCP config | `~/.continue/config.json` (add `mcpServers` key) |
| Zed | context server | `~/.config/zed/settings.json` (add `context_servers` key) |
| GitHub Copilot | instructions | `.github/copilot-instructions.md` (append Nexus + RTK guidance) |
| Amp | MCP/settings | `~/.config/amp/settings.json` (format needs confirmation — dry-run first) |

PearAI and JetBrains deferred (cloud/plugin-only, not local auto-connect).

Each target follows existing `nexus-doctor` pattern:
1. Add entry to `integrations/doctor/targets.json`
2. Add writer function or reuse existing `envfile`/`mcpServers`/`instructions` kind handlers
3. Add to dry-run output table

### 15. Graph Explorer UI Tab (ui-ux-roadmap.md Phase 5)
**Why:** Dashboard has 7 tabs but no entity graph visualization — it's in the roadmap and the data exists in `entities` + `relations` tables.

**Files:**
- `app/main.py` (dashboard HTML) — add Graph tab after Sessions tab
- `app/routers/agents.py` or new `app/routers/graph.py` — add data endpoint

**Backend endpoint:**
```python
GET /v1/graph?agent_id=&limit=100
# Returns: {nodes: [{id, name, entity_type, memory_count}], edges: [{from, to, relation_type, valid_until}]}
# Query: JOIN entities + relations, filter by agent, limit nodes by memory_count DESC
```

**Frontend:** inline SVG force-directed graph using D3-lite approach — no build pipeline needed. Nodes = entities, edges = relations, click node → shows connected memories.

---

## Ordering / Dependencies

```
Sprint 1 (Days 1-3):   Items 1, 2     — benchmarks first so we can measure everything else
Sprint 2 (Days 3-6):   Items 3, 4, 5  — recall quality improvements
Sprint 3 (Days 6-9):   Items 6, 7     — observability + privacy
Sprint 4 (Days 9-13):  Items 8, 9, 10 — infra/DX
Sprint 5 (Days 13-16): Items 11, 12   — dashboard + federation
Sprint 6 (Days 16-19): Items 13, 14, 15 — doc audit gaps (project API, doctor agents, graph UI)
```

## Key Files Summary

| Item | Primary Files |
|------|--------------|
| LongMemEval-S | `scripts/nexus-eval` |
| Coding evals | `scripts/nexus-eval` |
| Local reranker | `app/search/rerank.py`, `app/config.py`, `requirements.txt` |
| Confidence decay | `app/memory/consolidate.py`, `app/config.py` |
| Bi-temporal edges | `app/models/schema.py`, `app/main.py`, `app/search/graph.py` |
| OTEL | `app/main.py`, `app/memory/extract.py`, `app/routers/memory.py`, `requirements.txt` |
| Privacy/export | `app/routers/agents.py`, `app/mcp.py` |
| Peer merge | `app/routers/agents.py`, `app/agents/peer.py`, `app/models/api.py` |
| Embedded mode | `nexus/cli.py`, `app/db.py`, `app/config.py` |
| Tree-sitter | `app/routers/synapse.py`, `requirements.txt` |
| Quality dashboard | `app/routers/admin.py`, `app/main.py` |
| Federation | `app/federation.py`, `app/routers/federation.py`, `app/config.py` |
| Project Intelligence API | `app/routers/synapse.py` |
| Doctor agent integrations | `scripts/nexus-doctor`, `integrations/doctor/targets.json` |
| Graph Explorer UI | `app/main.py`, `app/routers/graph.py` |
