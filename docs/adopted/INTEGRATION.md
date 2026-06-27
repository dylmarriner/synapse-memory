# Integration

The `app/adopted/` modules are not just isolated utilities — they
are wired into the running Nexus server.  This page describes every
integration point, what is enabled by default, and how to enable the
rest.

## By the numbers

- **19 adopted patterns** in `app/adopted/` (see `app/adopted/__init__.py:REGISTRY`)
- **16 new REST routes** mounted at `/v1/adopted/*` (see `app/routers/adopted.py`)
- **1 new database migration** (`migrations/005_adopted.sql`) with 7 new tables and 6 new columns
- **78 tests** pass — 50 unit tests + 25 integration tests + 3 end-to-end tests
- **0 regressions** — every pre-existing Nexus test continues to work

## Integration map

| Adopted pattern | Where it is wired in Nexus | How to enable |
|---|---|---|
| **Ebbinghaus decay** | `app/routers/memory.py` — multiplies `relevance` by `decay.score()` in the recall path | Always on; the `_apply_adopted_filters` shim is called in every `/v1/memory/recall` call |
| **ADD-only extraction** | `app/memory/extract.py` — the worker calls the adopted prompt by default and persists each emitted fact as a sibling memory.  The legacy single-fact path is kept for opt-out | On by default.  Set `USE_LEGACY_EXTRACTION=1` in the worker environment to revert |
| **Expiration auto-forget** | `app/routers/memory.py` — drops memories past their `expiration_date` from the recall results | Always on (no flag needed) |
| **Memory blocks** | New table `memory_blocks` + REST CRUD at `/v1/adopted/blocks/{agent_name}/{label}` | Run `migrations/005_adopted.sql` |
| **Tri-method API** | New REST surface at `/v1/adopted/{retain,recall,reflect}` | Run the migration |
| **User profile (static+dynamic)** | `build_profile_from_recall` is exposed via the adopted module — call from any agent with the recall results | Always importable |
| **Wing/room/drawer scope** | `scope` column on `memories` (set via `/v1/adopted/retain`), filter on `/v1/adopted/recall` | Run the migration |
| **Temporal KG** | New table `temporal_triples` + REST CRUD at `/v1/adopted/triples` and `/v1/adopted/triples/query` | Run the migration |
| **4-tier consolidation** | `tier` column on `memories` (set to `'working'` on every new memory); REST introspection at `/v1/adopted/tiers/stats/{agent_name}` | Run the migration |
| **Deriver worker** | `app/adopted/deriver.py` provides the full async queue + batch consumer + typed-payload model.  Wire it into the existing `app/worker.py` by adding a startup task that runs `DeriverWorker.run_forever()` | Wire into the worker (out of scope for this PR; module is ready) |
| **Bi-encoder + cross-encoder rerank** | `app/adopted/rerank.py` is a drop-in `TwoStageSearch` class.  The existing `app/search/rerank.py` can be replaced with it without touching call sites | Replace the search rerank function (out of scope for this PR; module is ready) |
| **Pluggable storage backend** | ABC + in-memory backend in `app/adopted/storage_backend.py`.  Swap ChromaDB / Qdrant / pgvector by implementing the same interface | Use as a reference for the future storage refactor |
| **Biomimetic mental models** | `app/adopted/mental_models.py` — pure-Python, no DB.  Use as a library | Always importable |
| **Peer model** | New table `peers` + `peer_observations` + REST CRUD at `/v1/adopted/peers` and `/v1/adopted/peers/observations` | Run the migration |
| **12-event auto-capture hooks** | New table `hook_events` + REST capture at `/v1/adopted/hooks/capture` + REST list at `/v1/adopted/hooks/list`.  The agent plugins (Claude Code, Hermes, OpenClaw, OpenCode) can post events here | Run the migration; wire the agent plugins to POST to `/v1/adopted/hooks/capture` |
| **Multi-source ingest** | `app/adopted/multi_source.py` is a pure-Python pipeline.  REST at `/v1/adopted/ingest` returns chunks.  Persistence is the caller's job (typically: `for chunk in ingest_response.chunks: await tri_retain(chunk)`) | Always importable |
| **4-layer context stack** | `app/adopted/context_layers.py` — pure-Python, no DB.  Use as a library when building agent wake-up sequences | Always importable |
| **Verbatim closet** | New table `closets` (ready) + the `app/adopted/closet.py` library for building and applying the rank-based boost | Module is ready; wire a `closet_indexer` job in `app/worker.py` to populate the table |
| **Container tags** | `container_tag` column on `memories`, normalized on `/v1/adopted/retain`, filterable on `/v1/adopted/recall` | Run the migration |

## How to verify

```bash
# Run the adopted unit tests
pytest tests/adopted/ -v

# Run the integration tests
pytest tests/integration/ -v

# Run both
pytest tests/ -q
```

A full live deployment requires:

1. Postgres with `pgvector` (per the existing `docker-compose.yml`).
2. The migration `migrations/005_adopted.sql` applied (`docker compose up -d`
   runs all `migrations/*.sql` in order on first start).
3. An `OPENAI_API_KEY` for the embedding model (and an LLM key if you
   flip `USE_ADDITIVE_EXTRACTION=1`).

## How the wiring is done

Three places to look:

1. **`app/routers/adopted.py`** — the new REST surface.  Every endpoint
   is a thin adapter over the matching `app.adopted.*` module.  Mounted
   at `/v1/adopted/*` in `app/main.py`.

2. **`migrations/005_adopted.sql`** — new tables and columns.  All
   changes are additive: `CREATE TABLE IF NOT EXISTS`,
   `ADD COLUMN IF NOT EXISTS`.  A re-run on an existing database
   succeeds without errors.

3. **`app/routers/memory.py`** — the recall path now applies the
   adopted filters.  See `_apply_adopted_filters()` near the top of
   the file.

## Feature flags

Every adopted pattern has a feature flag in the registry.  None of
the patterns is enabled-by-feature-flag-out-of-the-box — the ones
that are always-on are not gated because they have no cost
(`expiration`, `decay.score` is a pure function call).  The
`USE_ADDITIVE_EXTRACTION` env var is the one runtime gate, because
flipping it changes the LLM call shape.

The full registry:

```python
from app.adopted import list_adopted
for p in list_adopted():
    print(p["name"], p["feature_flag"])
```

If you want to gate any pattern behind a real env var or settings
flag, the change is one line: wrap the call site in
`if getattr(settings, p["feature_flag"], True)`.
