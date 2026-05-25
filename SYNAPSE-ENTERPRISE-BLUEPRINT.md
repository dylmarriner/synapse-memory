# Synapse Enterprise — Universal AI Brain Sync Platform

## Architectural Blueprint — Production v1.0

> Surpassing BrainSync in every dimension: multi-device mesh, multi-tenant SaaS,
> distributed cognitive memory, token optimization engine, enterprise governance.

---

## 1. Enterprise System Architecture

### Layer Diagram

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                        CLOUD CONTROL PLANE                          │
 │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
 │  │Auth/SAML │  │ Billing  │  │  Tenant  │  │  Usage Analytics  │  │
 │  │ (Keycloak)│  │ (Stripe) │  │ Manager  │  │  + ROI Dashboard  │  │
 │  └──────────┘  └──────────┘  └──────────┘  └───────────────────┘  │
 │  ┌──────────────────────────────────────────────────────────────┐  │
 │  │            Distributed Brain Core (Raft Cluster)             │  │
 │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │  │
 │  │  │ Global   │  │ Vector   │  │Graph     │  │ Consensus   │ │  │
 │  │  │ Index    │  │ Store    │  │ Engine   │  │ (Raft)      │ │  │
 │  │  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │  │
 │  └──────────────────────────────────────────────────────────────┘  │
 │  ┌──────────────────────────────────────────────────────────────┐  │
 │  │               Message Bus / Event Stream                     │  │
 │  │        (NATS JetStream — cross-region replication)           │  │
 │  └──────────────────────────────────────────────────────────────┘  │
 └─────────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │   TAILSCALE MAGIC DNS      │
                    │  (ts-authkey, ACLs, tags)  │
                    └─────────────┬─────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
  ┌──────┴──────┐         ┌──────┴──────┐         ┌──────┴──────┐
  │ DEVICE A    │         │ DEVICE B    │         │ DEVICE C    │
  │ (Windsurf   │         │ (Hermes     │         │ (Paperclip  │
  │  IDE)       │         │  Server)    │         │  AI)        │
  └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
         │                        │                        │
  ┌──────┴──────┐         ┌──────┴──────┐         ┌──────┴──────┐
  │ LOCAL NODE  │         │ LOCAL NODE  │         │ LOCAL NODE  │
  │ RUNTIME     │         │ RUNTIME     │         │ RUNTIME     │
  │             │         │             │         │             │
  │ • SQLite    │         │ • SQLite    │         │ • SQLite    │
  │ • LanceDB   │         │ • LanceDB   │         │ • LanceDB   │
  │ • litefs    │         │ • litefs    │         │ • litefs    │
  │ • TEE       │         │ • TEE       │         │ • TEE       │
  └─────────────┘         └─────────────┘         └─────────────┘
         │                        │                        │
  ┌──────┴──────┐         ┌──────┴──────┐         ┌──────┴──────┐
  │ IDE Plugin  │         │ Hermes      │         │ Paperclip   │
  │ • Windsurf  │         │ Agent       │         │ Plugin      │
  │ • Antigrav  │         │ Plugin      │         │             │
  │ • VS Code   │         │             │         │             │
  └─────────────┘         └─────────────┘         └─────────────┘
```

### Multi-Region Deployment Strategy

```
      us-east-1                    eu-west-1                   ap-southeast-2
  ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
  │  Brain Core     │◄──────►│  Brain Core     │◄──────►│  Brain Core     │
  │  (Raft Leader)  │  NATS  │  (Raft Follower)│  NATS  │  (Raft Follower)│
  │                 │  JetS  │                 │  JetS  │                 │
  │  Global Index   │  tream │  Global Index   │  tream │  Global Index   │
  └────────┬────────┘        └────────┬────────┘        └────────┬────────┘
           │                          │                          │
      ┌────┴────┐               ┌────┴────┐               ┌────┴────┐
      │ Edge    │               │ Edge    │               │ Edge    │
      │ PoP     │               │ PoP     │               │ PoP     │
      └─────────┘               └─────────┘               └─────────┘
```

- **Raft consensus per tenant shard** — each tenant's data lives on a 3-node Raft group in the nearest region. Leader handles writes, followers serve reads.
- **NATS JetStream super-cluster** bridges regions. Each region runs a NATS leaf node connecting to a global mesh. Memory mutation events are replicated async with at-least-once delivery.
- **Edge PoPs** (Cloudflare Workers / Fly.io) terminate inbound MCP connections for geo-routing, TLS, and rate limiting.
- **Failover**: If the leader region goes dark, a Raft election promotes a follower in the next-closest region. DNS-based routing via the PoP layer redirects traffic.
- **DR**: Cross-region snapshot replication every 5 minutes. RPO = 5 min, RTO < 60 sec.

### Tenant Isolation Model

| Isolation Type | Freemium | Pro | Enterprise |
|---|---|---|---|
| Database | Shared schema with `tenant_id` column | Dedicated SQLite/LanceDB shard | Dedicated Raft cluster (3 nodes) |
| Encryption | AES-256 per-tenant key | AES-256 per-tenant key | Hardware-backed HSM per-tenant key |
| Compute | Shared Lambda pool | Reserved instances | Dedicated k8s namespace |
| Sync | Best-effort | Prioritized | Guaranteed <50ms sync latency |

---

## 2. Multi-Tenant SaaS Architecture (Monetization Core)

### Pricing Tiers

| Feature | Free | Pro ($29/mo) | Team ($99/mo) | Enterprise (custom) |
|---|---|---|---|---|
| Memory storage | 50 MB | 10 GB | 100 GB | Unlimited |
| Embeddings | 1K/mo | 100K/mo | 1M/mo | Unlimited |
| Daily sync ops | 500 | 10,000 | 100,000 | Unlimited |
| Devices | 2 | 10 | 25 | Unlimited |
| Sync latency | Best-effort | <200ms | <50ms | SLA-guaranteed |
| Retention | 7 days | 90 days | 1 year | Indefinite |
| Audit log | — | 30 days | 1 year | 7 years (SOC2) |
| SSO/SAML | — | — | ✓ | ✓ |
| Self-hosted | — | — | — | ✓ |
| SLA | None | 99.9% | 99.99% | 99.995% |

### Usage-Based Overages

- Storage: $0.50/GB/mo after base quota
- Embeddings: $0.001 per 1K embeddings
- Retrieval queries: $0.01 per 10K queries
- Sync bandwidth: $0.10/GB

### Billing Engine Architecture

```
  Stripe Billing ──► Billing API ──► Usage Aggregator ──► Tenant Quota Enforcer
       │                              │
       │                              ▼
       │                     ClickHouse (usage events)
       │                              │
       ▼                              ▼
  Subscription DB ──────────► Rate Limiter (Redis sorted sets)
```

- **Usage Aggregator**: Lambda that consumes sync operations, storage bytes, and embedding jobs from NATS, aggregates hourly, writes to ClickHouse.
- **Quota Enforcer**: Redis-based sliding window counter per tenant. Returns `429 Too Many Requests` with `X-RateLimit-Reset` header.
- **Stripe integration**: Webhook handler for subscription lifecycle. Pauses data ingestion on past-due accounts (read-only mode, data preserved 30 days).

### Admin Dashboard Metrics

- Total tokens saved per tenant (vs. baseline without Synapse)
- Retrieval latency p50/p95/p99 per region
- Sync throughput per device per tenant
- Embedding cache hit ratio
- Cost-per-query breakdown

---

## 3. MCP-Compatible Universal Memory Protocol

### Protocol Schema

```json
{
  "memory.store": {
    "params": {
      "project_key": "string (required, regex: ^[a-z0-9_-]{1,64}$)",
      "kind": "string (required, enum: working|episodic|semantic)",
      "content": {
        "text": "string (required, max: 200KB)",
        "embedding": "number[] (optional, auto-computed if omitted)",
        "metadata": {
          "title": "string (optional)",
          "tags": "string[] (optional)",
          "source": "string (optional, e.g. 'windsurf:windsurf', 'hermes:agent')",
          "importance": "number (optional, 0.0-1.0, default: auto-scored)",
          "ttl": "number (optional, seconds, default: 0=forever)"
        }
      },
      "context_id": "string (optional, for chunked storage)"
    },
    "returns": {
      "memory_id": "string (ULID)",
      "checksum": "string (SHA-256 of content.text)",
      "created_at": "number (epoch ms)",
      "context_id": "string (if chunked)",
      "total_chunks": "number (if chunked)"
    }
  },

  "memory.retrieve": {
    "params": {
      "query": "string (required, semantic search query)",
      "project_key": "string (optional, scopes to project)",
      "kinds": ["working" | "episodic" | "semantic"] (optional, default: all),
      "limit": "number (optional, default: 10, max: 100)",
      "min_score": "number (optional, 0.0-1.0, default: 0.5)",
      "temporal_decay": "boolean (optional, default: true)",
      "include_embeddings": "boolean (optional, default: false)"
    },
    "returns": {
      "results": [{
        "memory_id": "string",
        "score": "number (0.0-1.0)",
        "content": { "text": "string", "metadata": { ... } },
        "project_key": "string",
        "source": "string",
        "created_at": "number",
        "last_accessed": "number"
      }],
      "total_tokens_saved": "number",
      "latency_ms": "number"
    }
  },

  "memory.update": {
    "params": {
      "memory_id": "string (required)",
      "content": {
        "text": "string (optional)",
        "metadata": { ... } (optional partial merge)
      },
      "merge_strategy": "overwrite | merge | append (default: merge)"
    },
    "returns": {
      "memory_id": "string",
      "version": "number (monotonic)",
      "updated_at": "number"
    }
  },

  "memory.delete": {
    "params": {
      "memory_id": "string (required)",
      "reason": "string (optional, for audit trail)"
    },
    "returns": { "deleted": true }
  },

  "memory.sync": {
    "params": {
      "since": "number (optional, epoch ms, default: last_sync)",
      "device_id": "string (optional, scope to device)",
      "batch_size": "number (optional, default: 100)"
    },
    "returns": {
      "memories": [{
        "memory_id": "string",
        "version": "number",
        "operation": "create | update | delete",
        "content": { ... },
        "device_id": "string",
        "timestamp": "number"
      }],
      "checkpoint": "string (opaque cursor for next poll)",
      "has_more": "boolean"
    }
  },

  "memory.rank": {
    "params": {
      "project_key": "string (optional)",
      "limit": "number (optional, default: 50)",
      "min_importance": "number (optional, 0.0-1.0)"
    },
    "returns": {
      "ranked": [{
        "memory_id": "string",
        "importance_score": "number",
        "access_frequency": "number",
        "last_accessed": "number",
        "decay_factor": "number (0.0-1.0)",
        "suggested_action": "retain | compress | archive | evict"
      }]
    }
  },

  "memory.embed": {
    "params": {
      "texts": "string[] (required, batch up to 100)",
      "model": "string (optional, default: 'text-embedding-3-small')"
    },
    "returns": {
      "embeddings": ["number[][]"],
      "model": "string",
      "dimensions": "number"
    }
  },

  "memory.compress": {
    "params": {
      "memory_ids": "string[] (required)",
      "strategy": "deduplicate | summarize | prune_low_value (default: deduplicate)",
      "max_tokens": "number (optional, max output size)",
      "preserve_metadata": "boolean (default: true)"
    },
    "returns": {
      "compressed": [{
        "memory_id": "string",
        "original_tokens": "number",
        "compressed_tokens": "number",
        "compression_ratio": "number",
        "text": "string (compressed)",
        "strategy_applied": "string"
      }],
      "total_tokens_saved": "number",
      "evicted_ids": "string[]"
    }
  }
}
```

### Versioning — Event-Sourced + Vector Hybrid

- Each memory write creates an immutable event log entry (`sync_events` table). The current state is materialized from the latest event per memory_id.
- Each event carries a **vector clock** `{device_id: counter}` for conflict detection.
- The materialized `memories` table has a `version` column (monotonic per memory_id).
- When two devices write concurrently to the same memory_id, the vector clock detects the conflict and stores both versions with a `conflict_group` identifier.

### Conflict Resolution Strategy

```
Priority order:
1. If one version has source="user" and other has source="agent" → user wins
2. If vector clock shows causal ordering → the later event wins
3. If concurrent (causal gap) → merge via semantic similarity:
   a. Embed both texts
   b. Cosine similarity > 0.85 → auto-merge with append
   c. Cosine similarity < 0.85 → flag as manual review conflict
      Store in conflict_resolutions table with status="pending"
4. User-facing: expose conflict resolution via Dashboard + API
```

### Streaming Sync Protocol (WebSocket over Tailscale)

```
Client → Server:  {"type": "subscribe", "memory_ids": ["..."]}
Server → Client:  {"type": "delta", "memory_id": "...", "operation": "update",
                    "content": {...}, "version": 42}
Client → Server:  {"type": "ack", "memory_id": "...", "version": 42}
Server → Client:  {"type": "checkpoint", "cursor": "abc123"}
```

- **gRPC streaming** for high-throughput sync (preferred when both nodes are on Tailscale).
- **WebSocket fallback** for browser-based clients.
- **Delta compression** via `zstd` on the wire. Sync payloads are typically <5KB per delta.
- **Backpressure**: Server sends `X-Sync-Backoff: <seconds>` header when a tenant exceeds their rate limit.

---

## 4. Distributed Memory Intelligence Engine

### Three-Tier Cognitive Architecture

```
                         ┌─────────────────────┐
                         │   WORKING MEMORY     │
                         │  (Session context)   │
                         │  - ephemeral (<1hr)  │
                         │  - prompt injection  │
                         │  - sliding window    │
                         └──────────┬──────────┘
                                    │ promotes on access >3x
                                    ▼
                         ┌─────────────────────┐
                         │   EPISODIC MEMORY    │
                         │  (Timeline)          │
                         │  - actions + events  │
                         │  - temporal indexing │
                         │  - TTL-based decay   │
                         └──────────┬──────────┘
                                    │ consolidates via clustering
                                    ▼
                         ┌─────────────────────┐
                         │   SEMANTIC MEMORY    │
                         │  (Knowledge Graph)   │
                         │  - entity extraction │
                         │  - relationship map  │
                         │  - persistent        │
                         └─────────────────────┘
```

### Semantic Clustering Algorithm

```
function cluster_memories(memories[], config):
  # 1. Embed all memory texts
  embeddings = embed_batch([m.text for m in memories])

  # 2. HDBSCAN clustering with dynamic epsilon
  clusters = hdbscan(embeddings,
    min_cluster_size = max(3, len(memories) * 0.05),
    min_samples = 1,
    cluster_selection_epsilon = 0.4
  )

  # 3. Label noise points (cluster=-1) for individual storage
  for each memory where cluster == -1:
    assign as singleton

  # 4. Extract centroid summary for each cluster
  for each cluster:
    centroid = mean(embeddings[cluster.indices])
    representative = memories[argmin(||embeddings - centroid||)]
    cluster_summary = llm_summarize([
      m.text for m in memories[cluster.indices]
    ], max_tokens=200)

  return { clusters, centroids, summaries }
```

### Decay + Reinforcement Learning Model

```
importance_score(t) = base_importance
  × access_frequency_decay(t)
  × recency_bonus(t)
  × relationship_density(memory)

access_frequency_decay(t) = 1 / (1 + α · ln(1 + accesses_since_t))
recency_bonus(t)          = e^{-λ · (now - last_access)}
relationship_density(m)   = |edges_from(m)| / max_edges_in_graph

Where:
  α = 0.3 (decay aggressiveness, configurable per tenant)
  λ = 0.001 (recency half-life ~700 seconds)
```

Reinforcement signal: When a retrieved memory is followed within 5 turns by
another retrieval of the *same* memory, boost that memory's base_importance
by 10%. When a memory is retrieved but never referenced in the subsequent
prompt, reduce importance by 5%.

### Contradiction Resolution

```
1. On new memory write, compute embedding, search for neighbors with
   cosine_similarity > 0.7 AND kind = semantic

2. For each neighbor, run contradiction_check with an LLM:
   prompt: "Do these two statements contradict each other?
    A: '{new_text}'
    B: '{existing_text}'
    Answer: CONTRADICT | COMPATIBLE | DUPLICATE"

3. If CONTRADICT:
   a. Store both with a contradiction_link between them
   b. Boost both importance scores (contradictions are high-signal)
   c. Schedule periodic reconciliation via LLM summary pass
```

### Cross-Device Memory Merging

```
On sync from device B:
  For each incoming memory:
    if memory_id exists on this node (by ULID):
      merge using vector clock conflict resolution (see section 3)
    else:
      insert with source_device = device B

  Run cluster_merge on the combined set:
    if a new memory fits within epsilon of an existing cluster:
      recompute centroid, update cluster summary
    else:
      create new cluster (may trigger later cluster merge if density grows)
```

---

## 5. Token Optimization & Cost Reduction Engine

### Context Pruning Pipeline

```
                    ┌─────────────────────┐
  Raw prompt ──────►│ 1. Token Estimator  │──► estimated cost
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 2. Semantic Filter  │──► keep only memories
                    │    (retrieve top-k) │    with score > threshold
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 3. Deduplication    │──► remove exact + near-duplicate
                    │    (min-hash LSH)   │    text spans (Jaccard > 0.85)
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 4. Priority Ranking │──► sort by importance × recency
                    │    (RL-scored)      │    truncate to budget_tokens
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 5. TDD Compression  │──► dense serialization format
                    │    (Token-Dense     │    (<50% original tokens)
                    │     Dialect)        │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ 6. Prompt Assembly  │──► inject into system prompt
                    └─────────────────────┘
```

### Minimum Viable Context Injection (MVCI)

```python
def min_viable_context(query: str, memories: list, budget_tokens: int = 4096):
    """Return the smallest set of memories that can answer the query."""

    # Phase 1: Retrieve candidates
    candidates = vector_search(query, k=min(50, len(memories)))

    # Phase 2: Score candidates
    scored = []
    for m in candidates:
        token_count = estimate_tokens(m.text)
        relevance = cosine_sim(m.embedding, embed_query(query))
        value_per_token = (relevance * m.importance) / max(token_count, 1)
        scored.append((m, value_per_token))

    # Phase 3: Greedy knapsack selection
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = []
    used_tokens = 0
    for m, vpt in scored:
        tok = estimate_tokens(m.text)
        if used_tokens + tok <= budget_tokens:
            selected.append(m)
            used_tokens += tok
        if used_tokens >= budget_tokens * 0.9:
            break

    return selected
```

### Embedding Caching Strategy

- **Dense L2 cache (RAM)**: LRU with 10K entries per tenant. TTL = 5 minutes.
- **Entropy-based eviction**: If a cached embedding's source memory was read >5 times in the last hour, it stays. Otherwise, it's the first to be evicted.
- **Cross-tenant safe-shared cache**: Public embeddings (project_key is null) can be shared across tenants via a second-level Redis cluster. Only for semantic knowledge — never for user memory.
- **Pre-computation pipeline**: Background worker embeds new memories within 100ms of write. Stale embeddings are re-computed nightly.

### Cost Optimization Heuristics Engine

```
  CostPerQuery = (embedding_cost + retrieval_cost + storage_cost) × efficiency_factor

  Where:
    embedding_cost  = ∑(embedding_model.token_price × input_tokens)
    retrieval_cost  = ∑(vector_db_query_cost × query_count)
    storage_cost    = storage_bytes × $0.50/GB/mo
    efficiency_factor = 1.0 - (
        cache_hit_ratio × 0.3 +
        compression_ratio × 0.3 +
        dedup_ratio × 0.2 +
        mvci_savings_ratio × 0.2
      )

  Heuristic actions:
    If efficiency_factor < 0.6:
      - Increase MVCI aggressiveness (lower budget_tokens by 20%)
      - Rebuild embedding cache with higher priority
    If cache_hit_ratio < 0.3:
      - Expand L2 cache by 50%
      - Pre-compute embeddings for top-100 most accessed memories
    If compression_ratio < 0.5:
      - Apply LLM-based summarization on stale memories >7 days old
```

### ROI Dashboard Metrics

| Metric | Calculation |
|---|---|
| Total tokens saved | ∑(raw_tokens_in - compressed_tokens_out) |
| Cost saved ($) | tokens_saved × avg_cost_per_token (tenant's model mix) |
| Compression ratio | (1 - compressed_size / raw_size) × 100% |
| Cache hit ratio | cache_hits / total_retrievals |
| Avg latency impact | (retrieval_time + injection_time) per request |
| Smarts-per-token | relevance_score / tokens_consumed |

---

## 6. Tailscale-Based Secure Mesh Sync Layer

### Node Discovery

```
1. On startup, each local node calls the Brain Core registration API:
   POST /api/v1/nodes/register
   {
     "device_id": "ts-<tailscale-device-id>",
     "tailscale_ip": "100.x.y.z",
     "hostname": "my-device",
     "public_key": "<curve25519-public-key>",
     "capabilities": ["vector_store", "embedding", "sync"],
     "tenant_id": "tnt_abc123"
   }

2. Brain Core returns a manifest of peer nodes:
   {
     "peers": [
       {"device_id": "...", "tailscale_ip": "100.x.y.z",
        "public_key": "...", "last_seen": "...",
        "region": "us-east-1"}
     ],
     "credentials": {
       "sync_api_key": "sk_sync_...",
       "ts_auth_key": "tskey-auth-..."
     }
   }

3. p2p sync is established directly over Tailscale WireGuard.
   No cloud relay for data — only for discovery + signaling.
```

### Conflict Resolution Rules (Extended)

```
Rule 1 — Source priority: user > agent > system > tool
  user writes always take precedence over automated writes

Rule 2 — Recency: within same source tier, newer wins
  tiebreaker by vector clock counter

Rule 3 — Semantic merge: concurrent writes to the same memory
  If cosine_similarity(content_a, content_b) > 0.85:
    => combine with append, store as merged version
  Else:
    => flag as conflict, store both, notify tenant admin

Rule 4 — Trust score: devices with longer uptime + fewer
  conflict flags get priority weight in ambiguous cases

Rule 5 — Deleted wins: explicit deletion always synchronizes
  as authoritative tombstone, overriding any concurrent writes
```

### Delta-Based Sync Compression

```
1. Compute diff between local memory state and remote checkpoint:
   using Merkle tree of memory IDs + versions

2. For each divergent memory:
   a. If version(N+1) follows version(N) on same device:
      → send only the field-level JSON patch (RFC 6902)
   b. If versions diverged (concurrent writes):
      → send full memory object with conflict flag

3. Wire format: zstd-compressed NDJSON over gRPC bi-directional stream

4. Typical delta size:
   - 100 memories with minor changes: ~2KB compressed
   - Full sync of 10,000 memories (first run): ~500KB compressed
```

### Offline-First Operation

```
1. All writes go to local SQLite immediately (latency: <5ms)
2. WAL journal records every mutation with:
   - operation (create/update/delete)
   - vector clock tick
   - wall clock timestamp

3. On connectivity restored:
   a. Rapid sync: send WAL since last acknowledged checkpoint
   b. Brain Core replays events in causal order per memory_id
   c. Conflict resolution applied at the core
   d. Core responds with merged state + any remote updates
   e. Local node replays core's merged state into local SQLite

4. Conflict notifications queued for user review in Dashboard
```

### Device Identity + Revocation

- Each device generates a Curve25519 keypair on first launch
- Public key registered with Brain Core during onboarding
- Tailscale device identity (device ID from Tailscale API) is the primary key
- Revocation: Tenant admin removes device from Dashboard → Core broadcasts
  a `device_revoked` event via NATS → all nodes remove that device's
  public key from their p2p whitelist → sync with that device drops
- Tailscale ACLs can additionally restrict which nodes can talk to each other

---

## 7. Edge Runtime (Local Brain Node)

### Architecture (Per-Device Process)

```
  ┌──────────────────────────────────────────────┐
  │         LOCAL BRAIN NODE (synapse-node)       │
  │                                                │
  │  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
  │  │ LLM      │  │ Memory   │  │ Sync        │ │
  │  │ Intercept│  │ Vault    │  │ Daemon      │ │
  │  │ Middlewar│  │ (SQLCiph)│  │ (gRPC+WS)   │ │
  │  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
  │       │              │               │        │
  │  ┌────┴──────────────┴───────────────┴──────┐ │
  │  │         Embedded Vector DB (LanceDB)      │ │
  │  └───────────────────────────────────────────┘ │
  │  ┌───────────────────────────────────────────┐ │
  │  │         Local Embedding Runtime (onnx)     │ │
  │  │         • BGE-small-en-v1.5 ~33MB         │ │
  │  │         • ONNX CPU inference <10ms        │ │
  │  └───────────────────────────────────────────┘ │
  │  ┌───────────────────────────────────────────┐ │
  │  │         FUSE Filesystem (litefs)           │ │
  │  │         • Active DB: /var/lib/synapse/data │ │
  │  │         • Replicated via Tailscale p2p     │ │
  │  └───────────────────────────────────────────┘ │
  └───────────────────────────────────────────────┘
```

### Technologies

| Component | Choice | Rationale |
|---|---|---|
| Vector DB | LanceDB (embedded) | Columnar, b-tree + IVF-PQ, SQL bindings, 0 deps |
| Relational | SQLite + WAL + litefs | Battle-tested, litefs gives p2p replication |
| Encryption | SQLCipher + per-tenant key | AES-256, zero-config, FIPS 140-2 |
| Embedding | ONNX + BGE-small-en-v1.5 | 384-dim, <10ms CPU, no GPU needed |
| Wire sync | gRPC + WebSocket | gRPC for high-throughput, WS for browser |
| Orphan detection | systemd notify + health endpoint | Auto-restart, metrics to Cloud |

### LLM Request Interception Middleware

```typescript
// SDK middleware pattern — intercepts any outgoing LLM request
const synapse = new SynapseClient({ tenant: "tnt_abc123" });

const llmHandler = synapse.createMiddleware({
  beforePrompt: async (prompt, context) => {
    // 1. Extract intent via lightweight query classifier
    const intent = classify(prompt);

    // 2. Retrieve only relevant memories (MVCI)
    const memories = await synapse.retrieve({
      query: prompt,
      kinds: [intent.kind],
      limit: intent === "code_gen" ? 5 : 15,
    });

    // 3. Compress into TDD format
    const compressed = await synapse.compress(
      memories.map(m => m.memory_id),
      { strategy: "summarize", max_tokens: 2048 }
    );

    // 4. Inject into system prompt
    return {
      augmentedPrompt: injectContext(prompt, compressed),
      metadata: {
        tokens_saved: compressed.total_tokens_saved,
        memories_used: compressed.compressed.length,
      },
    };
  },

  afterResponse: async (response, context) => {
    // Extract any new facts from the response
    const facts = extractKeyFacts(response.text, context);
    for (const fact of facts) {
      await synapse.store({
        kind: "episodic",
        content: { text: fact, source: context.tool },
        metadata: { importance: 0.6 },
      });
    }
  },
});
```

### Prompt Injection Optimizer

```python
class PromptInjectionOptimizer:
    """Runs in the Local Node before any LLM call."""

    def optimize(self, prompt: str, memories: list) -> str:
        # 1. Remove redundant context
        deduped = self._deduplicate(prompt)

        # 2. Replace long literal blocks with references
        referenced = self._externalize_blobs(deduped, memories)

        # 3. Apply TDD serialization
        tdd = self._to_token_dense_dialect(referenced)

        # 4. Trim to budget
        return self._budget_trim(tdd, max_tokens=8000)

    def _to_token_dense_dialect(self, text: str) -> str:
        """Convert verbose prose to TDD format."""
        # Prose: "The user prefers using axios for HTTP requests"
        # TDD:   "[pref] http:axios"
        #
        # Prose: "The authentication middleware checks JWT tokens"
        # TDD:   "[arch] authn:JWT -> middleware -> verify()"
        return re.sub(
            r"The (user|system|function) (.+?) for (.+?)[. ]",
            r"[ref] \2:\3\n",
            text
        )
```

### Performance Targets

| Operation | Target | Method |
|---|---|---|
| Local retrieval (exact) | <10ms | SQLite indexed by memory_id |
| Local retrieval (vector) | <40ms | LanceDB IVF-PQ with 100K vectors |
| Local store | <5ms | WAL-mode SQLite |
| Embedding (384-dim) | <10ms | ONNX CPU inference |
| Node-to-node sync (p2p) | <50ms | Tailscale WireGuard + gRPC |
| Node-to-cloud sync | <150ms | NATS JetStream (compressed) |
| Prompt injection overhead | <20ms | In-process middleware |
| Full offline capability | Instant | All data local |

---

## 8. Developer SDK & Ecosystem Platform

### TypeScript SDK

```typescript
import { Synapse } from "@synapse-ai/sdk";

const synapse = new Synapse({
  tenant: "tnt_demo",
  apiKey: process.env.SYNAPSE_API_KEY,
  deviceName: "my-laptop",
});

// Lifecycle hooks
synapse.on("memory.store", async (memory) => {
  console.log(`Stored: ${memory.memory_id}`);
});

synapse.on("memory.retrieve", async (query, results) => {
  analytics.track("retrieval", {
    query_length: query.length,
    result_count: results.length,
    tokens_saved: results.reduce((a, r) => a + r.tokens_saved, 0),
  });
});

// Core operations
await synapse.store({
  kind: "semantic",
  content: {
    text: "The auth system uses JWT with RS256 signing, keys rotated every 90 days",
    metadata: { tags: ["auth", "security", "architecture"], source: "hermes" },
  },
});

const results = await synapse.retrieve({
  query: "How are tokens signed?",
  limit: 5,
});

await synapse.sync(); // Manual sync trigger

// Embedding
const [vector] = await synapse.embed(["Custom embedding call"]);

// Compression
const compressed = await synapse.compress([results[0].memory_id], {
  strategy: "summarize",
  max_tokens: 100,
});

// Rank for importance-based eviction decisions
const ranking = await synapse.rank({ limit: 10 });
```

### Plugin Scaffolding for IDE Integration

```typescript
// windsurf-plugin/src/extension.ts
import { SynapsePlugin } from "@synapse-ai/windsurf-sdk";

export function activate(context: ExtensionContext) {
  const plugin = new SynapsePlugin({
    apiKey: context.secrets.get("synapse.apiKey"),
    projectRoot: workspace.rootPath,
  });

  // Capture file edits as working memory
  workspace.onDidChangeTextDocument(async (event) => {
    if (event.document.uri.scheme !== "file") return;

    await plugin.store({
      kind: "working",
      content: {
        text: `File: ${relativePath(event.document.uri)}
Context: ${getScopeContext(event)}
Edit: ${extractDiff(event)}`,
        metadata: {
          source: "windsurf:editor",
          tags: [languageFromPath(event.document.uri)],
        },
      },
    });
  });

  // Intercept agent prompts to inject relevant context
  plugin.interceptAgentPrompt(async (prompt) => {
    const context = await plugin.retrieve({
      query: prompt,
      kinds: ["semantic", "episodic"],
      limit: 10,
    });

    return {
      prompt: injectSynapseContext(prompt, context),
      stats: { memories_used: context.length },
    };
  });

  // Sync on focus change
  window.onDidChangeWindowState((e) => {
    if (e.focused) plugin.sync();
  });
}
```

### Python SDK

```python
from synapse_sdk import SynapseClient

client = SynapseClient(
    tenant="tnt_demo",
    api_key="sk_syn_...",
    device="hermes-server-1",
)

# Use as context manager for auto-cleanup
with client:
    # Store
    mem = client.store(
        kind="episodic",
        text="Deployment pipeline failed on staging at 14:32 UTC due to cert expiry",
        tags=["deploy", "incident", "staging"],
        importance=0.9,
    )

    # Retrieve with hybrid search
    results = client.retrieve(
        query="deployment failures last week",
        kinds=["episodic"],
        limit=5,
        min_score=0.6,
    )

    for r in results:
        print(f"[{r.score:.2f}] {r.content.text[:100]}")

    # Compress stale memories
    stale = client.rank(kinds=["episodic"], limit=100)
    client.compress([m.memory_id for m in stale], strategy="deduplicate")

    # Listen for real-time sync events
    @client.on("sync_delta")
    def handle_sync(delta):
        print(f"Device {delta.device_id} synced {delta.memory_id} v{delta.version}")
```

---

## 9. Storage, Indexing & Retrieval System

### Hybrid Storage Hierarchy

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                        CLOUD TIER                               │
  │  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
  │  │ PostgreSQL      │  │ LanceDB          │  │ Redis         │  │
  │  │ (relational)    │  │ (distributed)    │  │ (cache)       │  │
  │  │ • tenants       │  │ • global vectors  │  │ • embeddings  │  │
  │  │ • projects      │  │ • tenant shards   │  │ • recent      │  │
  │  │ • audit_log     │  │ • IVF-PQ index    │  │ • hot results │  │
  │  │ • billing       │  └──────────────────┘  └───────────────┘  │
  │  └─────────────────┘                                            │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │ sync via NATS + gRPC
  ┌──────────────────────────────┴──────────────────────────────────┐
  │                        LOCAL TIER (Per Device)                   │
  │  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
  │  │ SQLite (WAL)    │  │ LanceDB          │  │ L1 Cache      │  │
  │  │ • memories      │  │ (local vectors)  │  │ (in-memory)   │  │
  │  │ • projects      │  │ • 100K vectors   │  │ LRU 10K entry │  │
  │  │ • files         │  │ • IVF-PQ index   │  │ <1μs lookup   │  │
  │  │ • sync_log      │  │ • <40ms query    │  └───────────────┘  │
  │  └─────────────────┘  └──────────────────┘                    │
  └────────────────────────────────────────────────────────────────┘
```

### Hybrid Retrieval Pipeline

```
                    ┌────────── User Query ──────────┐
                    │                                 │
                    ▼                                 ▼
         ┌──────────────────┐            ┌──────────────────┐
         │  Semantic Branch │            │  Keyword Branch  │
         │  (embed query)   │            │  (BM25 / FTS5)   │
         │                  │            │                  │
         │  1. Check L1     │            │  1. Tokenize     │
         │     cache (Redis)│            │     query        │
         │  2. LanceDB      │            │  2. SQLite FTS5  │
         │     ANN search   │            │     search       │
         │  3. Score by     │            │  3. Score by     │
         │     cosine_sim   │            │     BM25 rank    │
         └────────┬─────────┘            └────────┬─────────┘
                  │                               │
                  └───────────┬───────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Fusion (RRF)      │
                    │  Reciprocal Rank   │
                    │  Fusion algorithm  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Temporal Weight   │
                    │  decay_factor(t)   │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Tenant Scoping    │
                    │  WHERE tenant_id=  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Top-N Results     │
                    └────────────────────┘
```

### Caching Strategy

| Layer | Type | Size | Eviction | Latency |
|---|---|---|---|---|
| L1 | In-memory LRU | 10K entries | Entropy-based | <1μs |
| L2 | Redis | 100K entries | LRU + TTL 5min | <1ms |
| L3 | Cloud LanceDB | Full tenant | None (primary) | <10ms |
| L4 | Local LanceDB | 100K vectors | LRU per device | <40ms |

### Replication Model Across Tailscale Mesh

```
  Node A (laptop)      Node B (server)       Node C (cloud)
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │ SQLite WAL   │    │ SQLite WAL   │    │ PostgreSQL   │
  │ → litefs     │◄──►│ → litefs     │◄──►│ ← pglogical  │
  │              │    │              │    │              │
  │ LanceDB      │    │ LanceDB      │    │ LanceDB      │
  │ → custom p2p │◄──►│ → custom p2p │◄──►│ → gRPC proxy │
  └──────────────┘    └──────────────┘    └──────────────┘
        │                   │                    │
        └───────────────────┴────────────────────┘
                    Tailscale WireGuard
```

- **litefs**: FUSE-based replication for SQLite. Writes are forwarded to a
  "primary" node within the mesh. All nodes can serve reads from local
  SQLite. Primary can be any node — designated by lowest latency to cloud.

- **LanceDB custom p2p**: Each node maintains a Merkle tree of vector IDs.
  On sync, exchange Merkle roots, then only transfer divergent branches.

---

## 10. Security, Compliance & Enterprise Governance

### End-to-End Encryption

```
  Per-tenant key hierarchy:

  Master Key (HSM)                  ─ stored in AWS KMS / Azure Key Vault
    │
    ├── Tenant Root Key (TRK)       ─ derived from Master Key + tenant_id
    │     │
    │     ├── Data Encryption Key   ─ encrypts memory text at rest
    │     ├── Search Key            ─ blind index for encrypted search
    │     └── Sync Key             ─ authenticates p2p sync messages
    │
    └── Device Key (per device)     ─ signed by TRK, exchanged via Tailscale

  Encryption domains:
  - memory.content.text:     AES-256-GCM with DEK (different IV per row)
  - memory.content.metadata: AES-256-GCM with DEK (tags can be blind-indexed)
  - memory.embedding:        Optional encryption via FHE (overhead 10x, only for
                             compliance-hardened enterprise deploy)

  Key rotation:
  - TRK: quarterly, with re-wrap of all DEKs
  - Device keys: on device revocation
  - DEKs: per-write with key rotation on change
```

### Zero-Trust Architecture

```
  Every request is authenticated, authorized, and encrypted — regardless
  of network origin.

  1. No implicit trust for internal network traffic
  2. Tailscale identity is verified per-sync (mTLS over WireGuard)
  3. Cloud API: Bearer token (JWT signed by tenant root key)
  4. Local IPC: Unix domain socket + peer credential check
  5. Every memory access logged with device_id, tool, timestamp
```

### Audit Log Schema

```sql
CREATE TABLE audit_log (
    id          TEXT PRIMARY KEY,  -- ULID
    tenant_id   TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,  -- epoch ms
    device_id   TEXT NOT NULL,
    operation   TEXT NOT NULL,     -- store | retrieve | update | delete | sync
    memory_id   TEXT,              -- nullable for list/delete operations
    project_key TEXT,
    tool        TEXT,              -- e.g. "hermes:agent", "windsurf:editor"
    metadata    TEXT,              -- JSON: {query_hash, result_count, ...}
    ip_address  TEXT,
    user_agent  TEXT,
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- SOC2 requirement: audit_log is append-only (immutable)
-- Retention: 7 years for Enterprise, 1 year for Pro, 30 days for Free

CREATE TRIGGER audit_log_immutable
    BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
```

### GDPR Deletion Compliance

```python
async def delete_tenant_data(tenant_id: str):
    """GDPR Article 17 — Right to erasure ('Right to be forgotten')."""

    # 1. Mark tenant as deleting (read-only mode)
    await db.tenants.update(
        {"id": tenant_id},
        {"$set": {"status": "deleting", "deletion_requested_at": now()}}
    )

    # 2. Stop all sync activity (NATS consumer group pause)
    await nats.pause_consumer(f"tenant_{tenant_id}_*")

    # 3. Delete cloud data
    await pg.execute("DELETE FROM memories WHERE tenant_id = $1", tenant_id)
    await pg.execute("DELETE FROM projects WHERE tenant_id = $1", tenant_id)
    await pg.execute("DELETE FROM audit_log WHERE tenant_id = $1", tenant_id)
    await pg.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    await lancedb.delete_tenant(tenant_id)

    # 4. Broadcast purge signal to all local nodes
    await nats.publish(f"tenant.{tenant_id}.purge", {"reason": "GDPR deletion"})

    # 5. Verify within 30 days (GDPR SLA)
    await schedule_verification(tenant_id, delay_days=25)
```

### Permission Scopes

```json
{
  "scopes": {
    "memory:read": "Read memories (default for all tools)",
    "memory:write": "Create/update memories",
    "memory:delete": "Delete memories",
    "memory:sync": "Trigger or receive sync",
    "embedding:create": "Generate embeddings",
    "embedding:read": "Read existing embeddings",
    "admin:tenant": "Modify tenant settings",
    "admin:billing": "View/manage billing",
    "admin:devices": "Manage device registry",
    "admin:audit": "Read audit logs",
    "admin:users": "Manage team members (Enterprise)"
  }
}
```

---

## 11. Scalability & Performance Engineering

### Horizontal Scaling

```
  ┌──────────────────────────────────────────────────────────┐
  │                    Global Load Balancer                   │
  │  (Cloudflare / Fly Anycast / NS1)                        │
  └────┬────────────┬────────────┬────────────┬──────────────┘
       │            │            │            │
  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐
  │ Edge PoP│  │ Edge PoP│  │ Edge PoP│  │ Edge PoP│
  │ us-east │  │ eu-west │  │ ap-sg   │  │ sa-east │
  │ ┌──────┐│  │ ┌──────┐│  │ ┌──────┐│  │ ┌──────┐│
  │ │Brain  ││  │ │Brain  ││  │ │Brain  ││  │ │Brain  ││
  │ │Core   ││  │ │Core   ││  │ │Core   ││  │ │Core   ││
  │ │Raft   ││  │ │Raft   ││  │ │Raft   ││  │ │Raft   ││
  │ │Group  ││  │ │Group  ││  │ │Group  ││  │ │Group  ││
  │ └──────┘│  │ └──────┘│  │ └──────┘│  │ └──────┘│
  └─────────┘  └─────────┘  └─────────┘  └─────────┘
       │            │            │            │
       └────────────┴────────────┴────────────┘
                    NATS JetStream Super-Cluster
                       (cross-region bridge)
```

- **Per-tenant Raft shard**: Each tenant's data maps to a specific Raft group
  based on `hash(tenant_id) % num_shards`. Shards are distributed across
  regions for geo-locality.
- **Auto-shard splitting**: When a shard exceeds 100GB or 10M memories,
  it splits into two. The orchestrator moves half the data to a new Raft
  group, with a NATS stream bridge during migration.
- **Read replicas**: Each Raft follower serves reads. Additional read-only
  replicas can be provisioned per-region for low-latency queries.

### Sync Throughput Optimization

```
  Bottleneck analysis:
  ┌─────────────────┬──────────────────┬──────────────────────┐
  │ Bottleneck      │ Current limit    │ Mitigation           │
  ├─────────────────┼──────────────────┼──────────────────────┤
  │ Embedding API   │ 500 req/s (per   │ Local ONNX inference │
  │ (cloud)         │ deployment)      │ + batch queue        │
  ├─────────────────┼──────────────────┼──────────────────────┤
  │ SQLite writes   │ ~5,000 txn/s     │ WAL mode + batch     │
  │                 │ (per node)       │ inserts per sync     │
  ├─────────────────┼──────────────────┼──────────────────────┤
  │ Tailscale p2p   │ ~200 Mbps (per   │ Delta compression +  │
  │ bandwidth       │ connection)      │ selective sync       │
  ├─────────────────┼──────────────────┼──────────────────────┤
  │ NATS JetStream  │ ~1M msg/s (per   │ Partition by tenant  │
  │                 │ cluster)         │ + batch acks         │
  └─────────────────┴──────────────────┴──────────────────────┘
```

### Failure Recovery & Partition Tolerance

```
  Scenario 1: Node goes offline
    - Other nodes continue operating normally
    - Memos for offline node buffered in local WALs
    - On reconnect: rapid sync via Merkle tree exchange
    - Catch-up rate: ~10K memories/sec over Tailscale

  Scenario 2: Cloud control plane unavailable
    - Local nodes operate fully offline with all functionality
    - Sync between Tailscale peers continues (p2p mode)
    - Cloud-dependent features (billing, admin dashboard)
      degrade gracefully with cached last-known state

  Scenario 3: Network partition between two devices
    - Both devices continue writing locally
    - Conflict resolution handles divergent state on reconnection
    - Vector clock ensures eventual consistency
    - Manual conflict review available via Dashboard if auto-merge fails

  Scenario 4: Corrupted local database
    - Automatic WAL replay on next startup
    - If WAL also corrupt → fall back to last healthy snapshot
    - Full resync from peer nodes or cloud
```

---

## 12. Advanced Enterprise AI Features (Differentiation Layer)

### Self-Improving Memory Prioritization

```
  RL-based importance scoring loop:

  1. A memory is retrieved
  2. Within the next 5 LLM turns, check if the memory was "used":
     - Did the prompt assembled from this memory get a high-quality response?
     - Measured by: response relevance score + user engagement (edits, accepts)
  3. If used → importance += 0.05
  4. If not used → importance -= 0.02
  5. If never used after 10 retrievals → demote to archive
  6. Archive is not retrieved by default but can be explicitly searched

  Result: The system learns which memories are actually valuable to the
  developer, not just which ones match a keyword.
```

### Predictive Context Preloading Engine

```python
class PredictivePreloader:
    """Anticipates what memories will be needed next."""

    def __init__(self, client: SynapseClient):
        self.client = client
        self.session_markov = MarkovChain(n=3)  # 3-gram

    def on_tool_call(self, tool_name: str, memory_ids: list[str]):
        """Train on observed tool-to-memory sequences."""
        for mid in memory_ids:
            self.session_markov.add_transition(
                state=tool_name,
                next_memory=mid,
            )

    async def preload(self, current_tool: str) -> list[dict]:
        """Predict and pre-fetch next memories."""
        candidates = self.session_markov.predict(current_tool, top_k=5)
        futures = [self.client.retrieve(
            memory_id=c.memory_id
        ) for c in candidates if not self._is_cached(c.memory_id)]

        return await asyncio.gather(*futures)

    def _is_cached(self, memory_id: str) -> bool:
        """Check L1 cache before fetching."""
        return memory_id in self.l1_cache
```

### Multi-Agent Shared Cognition via OpenClaw

```
  OpenClaw Agent A (code review)    OpenClaw Agent B (testing)
          │                                │
          │     Synapse Memory Graph        │
          │     ┌──────────────────┐        │
          └────►│ • Agent A found  │◄───────┘
                │   XSS in line 42 │
                │ • Agent B wrote  │
                │   test for XSS   │
                │ • Both tagged    │
                │   "CVE-2024-xxx" │
                └──────────────────┘
                    │         │
                    │         └──► Agent C (security review)
                    │             receives pre-loaded context
                    ▼             about the XSS without
            Agent D (docs)        re-querying
            generates patch
            notes automatically
```

### Global Enterprise Memory Graph Analytics

- **Entity graph**: Extract entities (functions, classes, configs, services)
  from semantic memories. Build a Neo4j graph of relationships.
- **Heat maps**: Which parts of the codebase generate the most retrievals?
  Which questions recur? Visualize in Dashboard.
- **ROI dashboards**: Per-team, per-project token savings, response time
  improvement, repetition reduction.
- **Contradiction alerts**: When two teams store contradictory information
  about the same service, flag it for resolution.

### Automated Cost Optimization Recommendations

```
  Weekly report sent to tenant admin:
  ┌────────────────────────────────────────────────────────┐
  │  Cost Optimization Report — Week 13                    │
  │                                                        │
  │  You saved $342.17 this week (vs. no Synapse)          │
  │  Your remaining inefficiency: 23%                      │
  │                                                        │
  │  Recommendations:                                      │
  │  ┌────────────────────────────────────────────────────┐│
  │  │ 1. Compress 147 stale episodic memories            ││
  │  │    → Save ~12K tokens/week                         ││
  │  │    → Estimated savings: $0.48/week                 ││
  │  ├────────────────────────────────────────────────────┤│
  │  │ 2. Increase MVCI aggressiveness from 4K→3K tokens  ││
  │  │    → Save ~15% per query                           ││
  │  │    → Estimated savings: $2.10/week                 ││
  │  ├────────────────────────────────────────────────────┤│
  │  │ 3. Enable local ONNX embedding                     ││
  │  │    → Eliminate $0.001/embedding cloud cost         ││
  │  │    → Estimated savings: $5.83/week                 ││
  │  └────────────────────────────────────────────────────┘│
  │                                                        │
  │  Apply all? [Yes] [No] [Later]                         │
  └────────────────────────────────────────────────────────┘
```

---

## 13. End-to-End Real-World Flow

### Complete Lifecycle Walkthrough

```
Time  Tool          Action                          Synapse Component
────  ────────────  ──────────────────────────────  ─────────────────────
T+0   Windsurf IDE  User opens file auth.ts         IDE plugin captures
                                                    file context: path,
                                                    language, scope

T+1   Windsurf IDE  User types: "Add rate           Plugin records working
                    limiting middleware"             memory entry:
                                                    {kind: "working",
                                                     text: "auth.ts →
                                                     add rate limiter"}

T+2   Windsurf AI   AI sends prompt to LLM          Synapse middleware
                                                    intercepts:
                                                    1. Extracts intent:
                                                       "modify auth.ts to
                                                       add rate limiting"
                                                    2. MVCI retrieves:
                                                       - module:rate-limiter
                                                       - note:existing
                                                         auth middleware
                                                       - project:config
                                                       (3 memories, 214
                                                        compressed tokens)
                                                    3. Injects into prompt:
                                                       +214 tokens instead
                                                       of ~2K raw context
                                                    → 89% token saved

T+3   Windsurf AI   AI generates code              Middleware captures
                                                    response as episodic
                                                    memory:
                                                    {kind: "episodic",
                                                     text: "Generated
                                                     rate-limit middleware
                                                     for auth.ts using
                                                     express-rate-limit"}

T+4   Tailscale     Synapse local node syncs        Delta sync: 3 new
                    working + episodic memories      memories, ~1KB total
                    to Hermes server node            zstd-compressed to
                    (cloud server, same tenant)      380 bytes over gRPC

T+5   Hermes Agent  User asks: "Document the        Synapse retrieve finds:
                    auth system"                     1. Working mem: new
                                                       rate limiter code
                                                    2. Episodic: generation
                                                       context + modules
                                                    3. Semantic: auth
                                                       architecture summary
                                                    Compressor deduplicates
                                                    overlapping text →
                                                    1,024 tokens injected
                                                    instead of 3,500 raw

T+6   PaperclipAI   Documentation generation        Synapse cross-tool
                                                    retrieval — Hermes
                                                    agent's episodic memory
                                                    visible to Paperclip
                                                    via same tenant:
                                                    {kind: "semantic",
                                                     text: "Auth system
                                                     uses JWT + rate
                                                     limiter on /api/*"}

T+7   OpenClaw      Multi-agent CI pipeline         Both agents share
                    (code review + testing)          Synapse memory:
                                                    - Code reviewer sees
                                                      "XSS in line 42"
                                                    - Test writer reads
                                                      "added rate limiter"
                                                    → No duplicate work
                                                    → Context preloaded

T+8  ─────────────  Token savings summary ─────────
     Total raw context without Synapse:    ~28,000 tokens
     Total with Synapse:                    ~3,200 tokens
     Compression ratio:                     88.6%
     Estimated cost saved:                  $0.18 (GPT-4 pricing)
     Time saved:                            ~30 seconds per interaction
```

### Memory Graph Evolution Over Time

```
Day 1:  [working] auth.ts → rate limiter
        [episodic] generated express-rate-limit middleware

Day 3:  [working] auth.ts → JWT verification fix
        [episodic] found bug in verify() — token expiry not checked
        [semantic] Auth architecture: JWT RS256, 90-day key rotation

Day 7:  Clustering merges all auth-related memories:
        Cluster "auth" (7 memories, centroid: Auth architecture + JWT)
          - 3 working (combined → 1 consolidated)
          - 3 episodic (de-duped → 2 kept)
          - 1 semantic (retained as-is)
        → Semantic memory updated with consolidated summary

Day 30: RL scoring shows auth cluster accessed 23x, high importance (0.92)
        Stale episodic memories about the rate-limiter generation
        (accessed 1x in 30 days) demoted to archive
        → Compression ratio: 94% from original 28 memories
```

---

## Implementation Roadmap

| Phase | Time | Deliverable |
|---|---|---|
| **P0** | Week 1-2 | Fork Synapse MCP → multi-project, multi-tenant schema |
| **P1** | Week 3-4 | Local node runtime: LanceDB + SQLCipher + ONNX |
| **P2** | Week 5-6 | Tailscale mesh sync: gRPC + delta compression + CRDT |
| **P3** | Week 7-8 | Cloud control plane: auth, tenant management, billing (Stripe) |
| **P4** | Week 9-10 | Cognitive memory engine: clustering, decay, contradictions |
| **P5** | Week 11-12 | Token optimization engine: MVCI, TDD, ROI dashboard |
| **P6** | Week 13-14 | SDKs: TypeScript + Python + IDE plugins |
| **P7** | Week 15-16 | Enterprise features: E2E encryption, audit, SSO, admin dashboard |
| **P8** | Week 17-18 | Beta launch + load testing + SOC2 prep |
