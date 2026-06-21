# Nexus — Unified Agent Memory Server

**Nexus** is the successor to the Synapse Memory project — a high-performance, multi-agent shared memory server powered by PostgreSQL, pgvector, Redis, and FastAPI.

It provides semantic, lexical, graph, and temporal memory recall for AI agents across a Tailscale mesh network. Agents connect via MCP (Model Context Protocol), REST API, or native plugins.

## Architecture

```
                    ┌─────────────┐
                    │   Agents    │
                    │ (Hermes,    │
                    │  Cline,     │
                    │  OpenCode,  │
                    │  Paperclip) │
                    └──────┬──────┘
                           │ MCP / REST
                    ┌──────▼──────┐
                    │   Nexus     │
                    │   FastAPI   │
                    └──┬──────┬───┘
               ┌───────▼┐  ┌─▼────────┐
               │Postgres │  │  Redis   │
               │+pgvector│  │  Cache   │
               │+HNSW    │  │ +Tasks   │
               └─────────┘  └──────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **Semantic Search** | Vector embeddings with pgvector HNSW indexing |
| **Lexical Search** | BM25-style full-text keyword matching |
| **Graph Search** | Entity-relation knowledge graph traversal |
| **Temporal Search** | Recency-weighted memory retrieval |
| **Fusion Ranking** | Reciprocal Rank Fusion across all search modes |
| **LLM Reflection** | Deep synthesis and insight extraction from memories |
| **Knowledge Graph** | Entities, relations, blast radius analysis |
| **Agent Registry** | Per-agent profiles, representations, conclusions |
| **Async Learning** | Background worker for embedding & consolidation |
| **Cross-Project Sync** | Synapse-compat projects, events, file indexing |
| **MCP Protocol** | Full MCP server (Streamable HTTP + SSE) |
| **REST API** | OpenAI-compatible endpoints for any client |
| **Dashboard** | Real-time web UI with live telemetry |
| **TTL/Expiry** | Time-based memory auto-expiration |
| **Audit Logging** | Complete event-sourced operation log |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Tailscale (for multi-device mesh)
- API key for embedding model (OpenAI or compatible)

### Run

```bash
# Clone & configure
git clone https://github.com/dylanmarriner/synapse-memory
cd synapse-memory
cp .env.example .env
# Edit .env with your API keys

# Start
docker compose up -d

# Check health
curl http://localhost:7777/health

# Verify MCP
curl -X POST http://localhost:7777/mcp \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}'
```

## API Endpoints

### REST API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/v1/memory/save` | Save a memory |
| POST | `/v1/memory/recall` | Search memories (4-mode fusion) |
| POST | `/v1/memory/reflect` | LLM synthesis over memories |
| GET | `/v1/agents/{id}/context` | Get agent context |
| POST | `/v1/agents/{id}/learn` | Teach an agent |
| GET | `/v1/agents/{id}/entities` | Get knowledge graph entities |
| POST | `/v1/synapse/projects/register` | Register project (synapse-compat) |
| POST | `/v1/synapse/projects/{key}/remember` | Store project memory |
| POST | `/v1/synapse/projects/{key}/recall` | Search project memories |
| POST | `/v1/synapse/projects/{key}/files/ingest` | Index a file |
| POST | `/v1/synapse/projects/{key}/files/search` | Search indexed files |
| GET | `/v1/synapse/projects` | List projects |
| GET | `/v1/synapse/projects/{key}/context` | Project context pack |
| GET | `/v1/synapse/projects/{key}/events` | Recent activity |
| GET | `/v1/synapse/health/synapse` | Synapse-compat health |

### MCP Tools (42+)

`memory_save`, `memory_recall`, `memory_reflect`, `memory_synthesize`,
`memory_save_lesson`, `memory_save_global`, `memory_note_to_agent`,
`memory_confirm`, `memory_contradict`, `memory_profile`, `memory_forget_by_query`,
`memory_extract_session`, `agent_context`, `agent_learn`, `agent_represent`,
`nexus_status`, `sys_core_01` through `sys_core_31`,
`register_project`, `remember`, `recall`, `ingest_file`, `search_files`,
`project_context`, `list_projects`, `recent_activity`, `synapse_compat_health`

## Client Configuration

### Hermes Agent
```bash
hermes mcp add nexus \
  --url http://<nexus-host>:7777/mcp \
  --auth header \
  # Enter NEXUS_SECRET as Bearer token
```

### Cline / Claude Desktop
See `integrations/mcp/claude-desktop.json`

### OpenCode
See `integrations/mcp/opencode.json`

### Paperclip
See `paperclip-plugin/`

### OpenClaw
See `openclaw-plugin/`

## Migration from Synapse

Nexus includes a full synapse-compatibility layer. All synapse tools are available
as MCP tools (`register_project`, `remember`, `recall`, etc.) and REST endpoints
under `/v1/synapse/`. All synapse data models (projects, file_index, events) are
fully supported with PostgreSQL backends.

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
cp .env.example .env

# Run locally (without Docker)
uvicorn app.main:app --host 0.0.0.0 --port 7777
```

## Performance

- **Search latency**: <50ms for 4-mode fusion recall
- **Throughput**: 500+ memories/sec with async worker
- **Scaling**: Horizontal via Postgres replicas, Redis cluster
