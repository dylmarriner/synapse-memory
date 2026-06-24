<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/dylanmarriner/synapse-memory/main/docs/nexus-banner-dark.svg">
    <img alt="Nexus" src="https://raw.githubusercontent.com/dylanmarriner/synapse-memory/main/docs/nexus-banner-light.svg" width="520">
  </picture>
</p>

<p align="center">
  <b>Unified Agent Memory Server</b><br>
  <i>Semantic · Lexical · Graph · Temporal — fused into one recall engine</i>
</p>

<p align="center">
  <a href="https://github.com/dylanmarriner/synapse-memory/actions"><img src="https://img.shields.io/github/actions/workflow/status/dylanmarriner/synapse-memory/ci.yml?branch=main&style=flat&logo=github&label=CI&color=22d3ee" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-34d399?style=flat" alt="License"></a>
  <a href="https://github.com/dylanmarriner/synapse-memory/releases"><img src="https://img.shields.io/github/v/release/dylanmarriner/synapse-memory?style=flat&logo=semver&color=a78bfa" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-fbbf24?style=flat&logo=python" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115+-059669?style=flat&logo=fastapi" alt="FastAPI"></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-17+-336791?style=flat&logo=postgresql" alt="PostgreSQL"></a>
  <a href="https://redis.io/"><img src="https://img.shields.io/badge/Redis-8+-DC382D?style=flat&logo=redis" alt="Redis"></a>
  <br>
  <a href="https://tailscale.com/"><img src="https://img.shields.io/badge/Tailscale-ready-06b6d4?style=flat&logo=tailscale" alt="Tailscale"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-2024--11--05-6366f1?style=flat" alt="MCP"></a>
  <a href="https://github.com/dylanmarriner/synapse-memory/stargazers"><img src="https://img.shields.io/github/stars/dylanmarriner/synapse-memory?style=flat&logo=github&color=fb923c" alt="Stars"></a>
  <a href="https://github.com/dylanmarriner/synapse-memory/pulls"><img src="https://img.shields.io/badge/PRs-welcome-4ade80?style=flat" alt="PRs Welcome"></a>
  <img src="https://img.shields.io/badge/status-production-34d399?style=flat" alt="Production Ready">
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-api">API</a> •
  <a href="#-client-integration">Clients</a> •
  <a href="docs/agent-connection-tailscale.md">Tailscale</a> •
  <a href="#-deployment">Deployment</a> •
  <a href="#-development">Development</a> •
  <a href="docs/architecture.html">Diagram →</a>
</p>

---

Nexus is a **high-performance shared memory server** for AI agent fleets. It gives every agent on your network instant access to durable, searchable, fused memory — across projects, sessions, devices, and agent types.

Powered by **PostgreSQL + pgvector + Redis**, Nexus provides **four parallel search modes** fused by Reciprocal Rank Fusion, delivering sub-50ms recall across thousands of memories.

> **Successor to Synapse Memory** — full backward compatibility with all synapse tools and data models.

## ✨ Features

<table>
<tr>
<td width="50%">

**🧠 Multi-Mode Search**
- **Vector** — semantic embedding search via pgvector HNSW
- **Lexical** — BM25-style full-text keyword matching
- **Graph** — entity-relation knowledge graph traversal
- **Temporal** — recency-weighted time decay retrieval
- **RRF Fusion** — reciprocal rank fusion across all modes

**🔗 MCP Protocol**
- 42+ MCP tools (Streamable HTTP + SSE)
- Full OpenAPI spec for REST clients
- Plugins for Hermes, Cline, OpenCode, Paperclip, OpenClaw

**📊 Agent Registry**
- Per-agent profiles with LLM-generated representations
- Durable conclusions & preferences
- Cross-session context persistence

</td>
<td width="50%">

**🗄️ Knowledge Graph**
- Named entities with typed relations
- Blast radius / dependency impact analysis
- Auto-extracted from memories

**⚡ Async Pipeline**
- Background embedding generation
- Scheduled memory consolidation
- LLM-powered reflection & synthesis
- Conflict detection & deduplication

**🛡️ Enterprise Ready**
- Bearer token authentication
- Event-sourced audit logging
- TTL memory expiration
- Real-time dashboard with SSE telemetry
- Docker Compose deployment

</td>
</tr>
</table>

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/dylanmarriner/synapse-memory
cd synapse-memory

# Configure
cp .env.example .env
# Edit .env — set NEXUS_SECRET and OPENAI_API_KEY

# Launch
docker compose up -d

# Verify
curl http://localhost:7777/health
```

That's it. Nexus is running with 42 MCP tools and a full REST API.

### Verify MCP

```bash
curl -s -X POST http://localhost:7777/mcp \
  -H "Authorization: Bearer $(grep NEXUS_SECRET .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' \
  | jq '.result.tools | length'
# → 42
```

### Save & Recall

```bash
# Save a memory
curl -s -X POST http://localhost:7777/v1/memory/save \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"content":"Nexus API runs on port 7777 with Bearer auth","importance":0.8,"tags":["nexus","api"]}'

# Search
curl -s -X POST http://localhost:7777/v1/memory/recall \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"query":"nexus api port","limit":5}'
```

## 🏗️ Architecture

<p align="center">
  <a href="docs/architecture.html">
    <img src="docs/architecture.html" alt="Nexus Architecture Diagram" width="90%" style="max-width: 900px; border-radius: 12px; border: 1px solid #1e293b;">
  </a>
  <br>
  <sub>📐 <a href="docs/architecture.html">Open full interactive architecture diagram →</a></sub>
</p>

### Data Flow

```
Agent → MCP Tool Call → FastAPI Gateway → Search Engine → pgvector/PostgreSQL → Fused Results
                                  ↓
                          Async Worker
                     (Embedding · Consolidation)
```

## 📡 API

### REST Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check |
| `POST` | `/v1/memory/save` | Save a memory |
| `POST` | `/v1/memory/recall` | 4-mode fused search |
| `POST` | `/v1/memory/reflect` | LLM reflection over memories |
| `POST` | `/v1/memory/synthesize` | Deep topic synthesis (via reflect) |
| `GET` | `/v1/agents/{id}/context` | Agent context pack |
| `POST` | `/v1/agents/{id}/learn` | Teach an agent |
| `GET` | `/v1/synapse/projects` | List Synapse-compat projects |
| `POST` | `/v1/synapse/projects/{key}/remember` | Project-scoped memory |
| `POST` | `/v1/synapse/projects/{key}/recall` | Project search |

### MCP Tools (42+)

```
memory_save                  memory_recall                 memory_reflect
memory_synthesize            memory_save_lesson            memory_save_global
memory_note_to_agent         memory_confirm                memory_contradict
memory_profile               memory_forget_by_query        memory_extract_session
agent_context                agent_learn                   agent_represent
nexus_status                 
session_start                session_append                session_end
session_get                  session_list
sys_core_01 — sys_core_31   (project context, code analysis, git diff, skills, task state)
register_project             remember                      recall
ingest_file                  search_files                  project_context
list_projects                recent_activity               synapse_compat_health
```

Full OpenAPI spec at `/.well-known/nexus/openapi.json` when running.

## 🔌 Client Integration

Use [`docs/agent-connection-tailscale.md`](docs/agent-connection-tailscale.md)
for the full cross-computer setup guide, including Tailscale, Nexus Doctor,
HTTP MCP, stdio MCP, REST/OpenAPI, and per-agent instructions.

For local auto-configuration, run:

```bash
scripts/nexus-doctor
scripts/nexus-doctor --apply --nexus-url http://<tailscale-host>:7777 --secret "$NEXUS_SECRET"
```

### Hermes Agent
```bash
hermes mcp add nexus --url http://<host>:7777/mcp --auth header
```
Then enter your `NEXUS_SECRET` as the Bearer token.

### Cline / Claude Desktop
```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://<host>:7777/mcp",
      "headers": { "Authorization": "Bearer <NEXUS_SECRET>" }
    }
  }
}
```
See [`integrations/mcp/`](integrations/mcp/) for ready-made config files.

### OpenCode
```bash
opencode mcp add nexus --url http://<host>:7777/mcp --auth header
```

### Paperclip
See [`paperclip-plugin/`](paperclip-plugin/) for the Paperclip AI plugin.

### OpenClaw
See [`openclaw-plugin/`](openclaw-plugin/) for the OpenClaw plugin.

## 🐳 Deployment

### Docker Compose (Recommended)

```bash
cp .env.example .env
# Edit .env with your secrets and API keys
docker compose up -d
```

Services:
- `nexus-api` — FastAPI application (port 7777)
- `nexus-worker` — Async embedding, extraction & consolidation worker
- `postgres` — PostgreSQL 17 + pgvector (port 5435)
- `redis` — Redis 8 (port 6381)

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXUS_SECRET` | ✅ | — | API auth token (shared with clients) |
| `OPENAI_API_KEY` | ✅ | — | For text-embedding-3-small |
| `DEEPSEEK_API_KEY` | — | — | For LLM reflection (falls back to OpenAI) |
| `EMBEDDING_MODEL` | — | `text-embedding-3-small` | Embedding model to use |
| `EMBEDDING_DIMS` | — | `384` | Vector dimension (text-embedding-3-small) |
| `LLM_MODEL` | — | `deepseek-chat` | Model for reflection/synthesis |
| `LEARNING_INTERVAL` | — | `300` | Consolidation interval (seconds) |
| `CORS_ORIGINS` | — | `*` | CORS allowed origins |
| `PORT` | — | `7777` | HTTP port |

### Standalone (No Docker)

```bash
pip install -r requirements.txt
cp .env.example .env
# Ensure PostgreSQL + Redis are running
uvicorn app.main:app --host 0.0.0.0 --port 7777
```

## 🛠️ Development

```bash
# Setup
git clone https://github.com/dylanmarriner/synapse-memory
cd synapse-memory
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Lint
ruff check app/
mypy app/
```

### Project Structure

```
nexus/
├── app/
│   ├── main.py              # FastAPI application
│   ├── mcp.py               # MCP protocol server (42+ tools)
│   ├── worker.py             # Async background worker
│   ├── models/               # SQLAlchemy ORM models
│   ├── routers/              # FastAPI route handlers
│   ├── search/               # Search engine (vector/lexical/graph/temporal)
│   ├── memory/               # Memory operations (ingest, reflect, consolidate)
│   └── agents/               # Agent registry & context
├── integrations/             # Client configs, MCP, plugins
├── migrations/               # Database migrations
├── scripts/                  # Deployment & utility scripts
├── sdk/                      # Python & TypeScript SDKs
└── docker-compose.yml        # Production deployment
```

## 📚 Documentation

- [Architecture Diagram](docs/architecture.html) — interactive SVG
- [Integration Guide](UNIVERSAL_AGENT_INTEGRATION.md)
- [Agent + Tailscale Connection Guide](docs/agent-connection-tailscale.md)
- [Nexus Doctor](docs/nexus-doctor.md)
- [RTK Integration](docs/rtk-integration.md)
- [MCP Plugin Examples](integrations/plugins/)
- [Agent Skills](integrations/skills/)
- [SDK Documentation](sdk/)

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/amazing`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push (`git push origin feat/amazing`)
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE).

---

<p align="center">
  <sub>Built with FastAPI · PostgreSQL · pgvector · Redis · Docker</sub><br>
  <sub>⭐ Star us on GitHub — it helps other agents find us</sub>
</p>
