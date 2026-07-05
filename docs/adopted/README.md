# Adopted Patterns

This directory holds patterns that Nexus has taken from the broader
ecosystem of memory systems and rewritten as Nexus-native modules.

The patterns are **not** wrappers around the upstream projects — they
are clean-room implementations that live under `app/adopted/` and
follow Nexus conventions.

## Pattern index

| Pattern | Module | What it does |
|---|---|---|
| Ebbinghaus + Hebbian + spacing decay | `decay.py` | Memory strength drifts toward a floor if untouched, grows on access, gains stability on spaced reinforcement. |
| ADD-only single-pass extraction | `prompts.py` | One LLM call that emits a JSON list of new memories, with observation-date anchoring and link IDs. |
| Expiration auto-forgetting | `expiration.py` | `expiration_date` metadata hides a memory from search after the date passes. |
| Named memory blocks | `blocks.py` | In-context labelled slots with `value` / `description` / `limit` / `read_only`, rendered as XML. |
| Three-method memory API | `tri_method.py` | `retain / recall / reflect` as the single user-facing surface. |
| Static + dynamic user profile | `profile.py` | One-call `profile(tag, q)` returning long-lived facts and recent context. |
| Wing/room/drawer scope | `scope.py` | Hierarchical scope: `auth.jwt.refresh`. Searches scope to a sub-tree. |
| Temporal knowledge graph | `temporal_kg.py` | Subject-predicate-object triples with `valid_from` / `valid_to` and `as_of` queries. |
| Four-tier consolidation | `tiers.py` | Working → episodic → semantic → procedural with per-tier decay. |
| Background deriver worker | `deriver.py` | Async queue + batch consumer + typed-payload tasks (`representation`, `summary`, `dream`, `reconciler`, `webhook`, `deletion`). |
| Bi-encoder + cross-encoder rerank | `rerank.py` | Two-stage retrieval: fast bi-encoder, precise cross-encoder. |
| Pluggable storage backend | `storage_backend.py` | ABC with capability tokens — swap ChromaDB/Qdrant/pgvector at will. |
| Biomimetic mental models | `mental_models.py` | Three memory kinds: world / experiences / mental_models. |
| Peer-centric model | `peers.py` | `(observer, observed)` peer-pair collections, multi-perspective. |
| 12-event auto-capture hooks | `hooks.py` | Lifecycle hooks that fire-and-forget every agent event into memory. |
| Multi-source ingest | `multi_source.py` | Ingest org / markdown / plaintext / pdf / notion / github / image / speech. |
| 4-layer context stack | `context_layers.py` | L0 identity / L1 essential / L2 on-demand / L3 deep search. |
| Verbatim closet | `closet.py` | Compact topic-pointer lines (`topic\|entities\|→drawer`) + rank-based rerank boost. |
| Container tags | `containers.py` | The scope key for every memory: `kind:name` with normalisation. |

## How to use a pattern

Every pattern is independently importable.  Most are pure-Python and
have no Nexus dependency at all.  The ones that talk to external
storage (storage_backend, deriver, hooks) ship in-memory
implementations that are useful for tests.

```python
from app.adopted import decay, profile, tri_method, scope

# Ebbinghaus-strengthened memory
state = decay.fresh()
state = decay.potentiate(state)            # touched
score = decay.score(state)                # current relevance

# User profile
p = profile.build_profile_from_recall([
    {"id": "1", "content": "User is a senior eng", "metadata": {"created_at": "2020-01-01"}, "score": 0.9},
    {"id": "2", "content": "Working on auth",     "metadata": {"created_at": "2025-06-01"}, "score": 0.7},
])
print(p.static, p.dynamic)

# Hierarchical scope
scope.matches("auth", "auth.jwt.refresh")  # True
scope.normalize("Auth/JWT  Refresh")      # "auth.jwt.refresh"

# Three-method API
m = tri_method.in_memory_tri_method()
m.retain("the Eiffel Tower is in Paris")
print(m.recall("where is the tower").results)
```

## How to test

```bash
pytest tests/adopted/ -v
```

The tests are pure-Python — no database, no network, no LLM.  They
exercise the public surface of each module with deterministic inputs.

## Why no attribution

The original sources of these patterns are deliberately not named in
the code.  This is not a license dodge — the implementations are
original, clean-room rewrites, not copies.  Rather, the package is
intended to be readable on its own: every module is its own
self-contained, well-named idea, with no requirement to read a paper
or chase a citation to understand what it does.

If you want to know which ecosystem project a given pattern was
inspired by, look at the git history of the file in question — every
adoption was a single commit with a thoughtful commit message.
