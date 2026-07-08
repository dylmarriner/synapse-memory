<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/dylmarriner/synapse-memory/main/docs/nexus-banner-dark.svg">
    <img alt="Nexus" src="https://raw.githubusercontent.com/dylmarriner/synapse-memory/main/docs/nexus-banner-light.svg" width="520">
  </picture>
</p>

<p align="center">
  <b>Unified Agent Memory Server</b><br>
  <i>Semantic · Lexical · Graph · Temporal — fused into one recall engine</i>
</p>

<p align="center">
  <a href="https://github.com/dylmarriner/synapse-memory/actions"><img src="https://img.shields.io/github/actions/workflow/status/dylmarriner/synapse-memory/ci.yml?branch=main&style=flat&logo=github&label=CI&color=22d3ee" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-34d399?style=flat" alt="License"></a>
  <a href="https://github.com/dylmarriner/synapse-memory/releases"><img src="https://img.shields.io/github/v/release/dylmarriner/synapse-memory?style=flat&logo=semver&color=a78bfa" alt="Version"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-fbbf24?style=flat&logo=python" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115+-059669?style=flat&logo=fastapi" alt="FastAPI"></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-17+-336791?style=flat&logo=postgresql" alt="PostgreSQL"></a>
  <a href="https://redis.io/"><img src="https://img.shields.io/badge/Redis-8+-DC382D?style=flat&logo=redis" alt="Redis"></a>
  <br>
  <a href="https://tailscale.com/"><img src="https://img.shields.io/badge/Tailscale-ready-06b6d4?style=flat&logo=tailscale" alt="Tailscale"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-2024--11--05-6366f1?style=flat" alt="MCP"></a>
  <a href="https://github.com/dylmarriner/synapse-memory/stargazers"><img src="https://img.shields.io/github/stars/dylmarriner/synapse-memory?style=flat&logo=github&color=fb923c" alt="Stars"></a>
  <a href="https://github.com/dylmarriner/synapse-memory/pulls"><img src="https://img.shields.io/badge/PRs-welcome-4ade80?style=flat" alt="PRs Welcome"></a>
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

Nexus is a **high-performance shared memory server** for AI agent fleets. It gives every agent on your network direct access to durable, searchable, fused memory across projects, sessions, devices, and agent types.

Powered by **PostgreSQL + pgvector + Redis**, Nexus provides **four parallel search modes** fused by Reciprocal Rank Fusion, delivering sub-50ms recall across thousands of memories.

> **Default runtime: direct agent-to-memory mode**
> The optional Living Mind / LLM layer is disabled by default. Nexus exposes the memory, agent, session, and MCP surfaces directly.

> **Successor to Synapse Memory** — backward compatible with the existing tools and data models.

## Runtime Modes

| Mode | Status | Notes |
|---|---|---|
| Direct agent-to-memory | Default | Agents call `memory_*`, `agent_*`, `session_*`, and MCP tools directly. |
| Living Mind / LLM layer | Disabled by default | Optional legacy layer for teams that explicitly enable it. |
| Embedded mode | Optional | Runs the extraction worker in-process for low-friction local installs. |

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
- Per-agent profiles with stored representations derived from conclusions and recent memories
- Durable conclusions & preferences
- Cross-session context persistence

**🧩 Adopted Patterns** (`app/adopted/`)
- 19 distinctive memory ideas, rewritten as Nexus-native modules
- Ebbinghaus decay, 4-tier consolidation, temporal KG, memory blocks,
  peer model, 12-event hooks, two-stage rerank, pluggable backend, and more
- Pure-Python, no DB, fully tested (50+ tests)

</td>
<td width="50%">

**🗄️ Knowledge Graph**
- Named entities with typed relations
- Blast radius / dependency impact analysis
- Auto-extracted from memories

**⚡ Async Pipeline**
- Background embedding generation
- Scheduled memory consolidation
- Deterministic reflection & synthesis
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
git clone https://github.com/dylmarriner/synapse-memory
cd synapse-memory

# Configure
cp .env.example .env
# Edit .env — set NEXUS_SECRET

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
| `POST` | `/v1/memory/reflect` | Deterministic reflection over memories |
| `POST` | `/v1/memory/synthesize` | Deterministic topic synthesis (via reflect) |
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

### 🚀 Quick install — one command, every agent

The fastest way to wire Nexus into any AI agent on this machine is the
universal installer. It auto-detects what's installed and uses each
agent's native install path (`opencode plugin`, `claude plugin install`,
Paperclip's `/api/plugins/install`, OpenClaw's plugin API, etc.) with
config-file fallbacks for agents that don't have a plugin install command.

```bash
# Local (from this repo):
scripts/nexus-install

# Or via one-liner (no clone required):
curl -fsSL https://raw.githubusercontent.com/dylmarriner/synapse-memory/main/scripts/nexus-install-remote.sh \
  | NEXUS_URL=http://<host>:7777 NEXUS_SECRET=<secret> bash

# Show what's supported + detection status:
scripts/nexus-install --list

# Install into specific agents:
scripts/nexus-install paperclip opencode openclaw hermes

# Install into everything (skip detection):
scripts/nexus-install --all
```

By default the installer writes three things per agent:

1. **Connection** — MCP server entry / plugin registration / config so the
   agent can actually call Nexus tools.
2. **Rules** (default on) — global instruction files (`~/.claude/CLAUDE.md`,
   `~/.gemini/GEMINI.md`, `~/.codex/AGENTS.md`, `~/.aider/CONVENTIONS.md`,
   etc.) that teach the agent *when* to use Nexus. Add `--no-rules` to
   install connection only.
3. **Skills** (opt-in: `--with-skills`) — a reusable `nexus-memory` skill
   agents can discover and invoke.
4. **Hooks** (opt-in: `--with-hooks`) — Claude Code event hooks
   (SessionStart, UserPromptSubmit, Stop) that auto-recall before each
   prompt and auto-save after each turn.

By default, rules and skills install **globally** (in `$HOME/...`) so they
apply to every project. Use `--local` to write them to the current
project's working directory instead.

```bash
# Connection + global rules (default)
scripts/nexus-install

# Connection + global rules + global skills + global hooks
scripts/nexus-install --with-skills --with-hooks

# Connection + project-level rules (for the current project only)
scripts/nexus-install --local

# Connection only, no rules
scripts/nexus-install --no-rules
```

Supports 28+ agents: Paperclip, OpenClaw, OpenCode, Claude Code, Hermes,
Claude Desktop, Cline, Cursor, VS Code, VSCodium, Windsurf, Antigravity,
Trae, PearAI, Gemini CLI, Qwen Code, Codex CLI, Aider, Devin CLI, Goose,
OpenHands, SWE-agent, Continue, Zed, Amp, GitHub Copilot — and the Cline
extension inside any VS Code-compatible IDE.

### Per-agent native install paths

If you'd rather use each agent's own install command directly:

```bash
# Paperclip (server-side plugin install)
curl -X POST http://127.0.0.1:3100/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"packageName":"/path/to/synapse-memory/paperclip-plugin","isLocalPath":true}'

# OpenClaw (server-side plugin install)
curl -X POST http://127.0.0.1:<openclaw-port>/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"packageName":"/path/to/synapse-memory/openclaw-integration/extensions/nexus-memory","isLocalPath":true}'

# OpenCode (npm plugin)
opencode plugin @nexus/memory --global
# Or as MCP:
opencode mcp add nexus-memory --url http://<host>:7777/mcp --header "Authorization=Bearer <NEXUS_SECRET>"

# Claude Code
claude plugin install integrations/plugins/claude-code

# Hermes (copy plugin + write env)
cp -r integrations/plugins/hermes-nexus ~/.hermes/hermes-agent/plugins/memory/nexus
echo 'NEXUS_URL=http://<host>:7777
NEXUS_SECRET=<secret>
NEXUS_AGENT_ID=hermes' > ~/.hermes/nexus.env
```

### What the installer writes

| Layer | What | Where (default = global) | Flag |
|---|---|---|---|
| Connection | MCP server / plugin registration | per-agent native location | always |
| Rules | "When to recall/save/reflect" guidance | `~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md`, `~/.codex/AGENTS.md`, `~/.aider/CONVENTIONS.md`, `~/.continue/NEXUS.md`, `~/.zed/AGENTS.md`, `~/.config/amp/AGENTS.md`, `~/.config/opencode/AGENTS.md`, … | default on (`--no-rules` to skip, `--local` for project) |
| Skills | Reusable `nexus-memory` skill | `~/.claude/skills/nexus-memory/SKILL.md`, `~/.config/opencode/skills/nexus-memory/SKILL.md`, `~/.continue/config.yaml` | `--with-skills` |
| Hooks | SessionStart + UserPromptSubmit + Stop | `~/.claude/settings.json` | `--with-hooks` |

Canonical sources:
[`integrations/rules/nexus-memory.md`](integrations/rules/nexus-memory.md)
and
[`integrations/skills/nexus-memory/SKILL.md`](integrations/skills/nexus-memory/SKILL.md).

### Cross-computer setup (Tailscale)

Use [`docs/agent-connection-tailscale.md`](docs/agent-connection-tailscale.md)
for the full cross-computer setup guide, including Tailscale, Nexus Doctor,
HTTP MCP, stdio MCP, REST/OpenAPI, and per-agent instructions.

For local auto-configuration, run:

```bash
scripts/nexus-doctor
scripts/nexus-doctor --apply --nexus-url http://<tailscale-host>:7777 --secret "$NEXUS_SECRET"
```

### Manual config snippets

If you need to write configs by hand:

**Hermes Agent**
```bash
hermes mcp add nexus --url http://<host>:7777/mcp --auth header
```
Then enter your `NEXUS_SECRET` as the Bearer token.

**Cline / Claude Desktop / Cursor / VS Code / Windsurf / Antigravity**
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

See [`integrations/mcp/`](integrations/mcp/) for ready-made config files
and [`integrations/plugins/install-registry.json`](integrations/plugins/install-registry.json)
for the full install registry.

### Plugin source trees

- Paperclip plugin: [`paperclip-plugin/`](paperclip-plugin/)
- OpenClaw extension: [`openclaw-integration/extensions/nexus-memory/`](openclaw-integration/extensions/nexus-memory/)
- OpenCode plugin (npm): [`integrations/plugins/opencode-nexus/`](integrations/plugins/opencode-nexus/)
- Claude Code plugin: [`integrations/plugins/claude-code/`](integrations/plugins/claude-code/)
- Hermes plugin: [`integrations/plugins/hermes-nexus/`](integrations/plugins/hermes-nexus/)
- Canonical rules: [`integrations/rules/nexus-memory.md`](integrations/rules/nexus-memory.md)
- Canonical skill: [`integrations/skills/nexus-memory/SKILL.md`](integrations/skills/nexus-memory/SKILL.md)

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
| `OPENAI_API_KEY` | Optional | — | For hosted text-embedding-3-small embeddings |
| `DEEPSEEK_API_KEY` | — | — | Optional legacy LLM-backed paths only |
| `EMBEDDING_MODEL` | — | `text-embedding-3-small` | Embedding model to use |
| `EMBEDDING_DIMS` | — | `384` | Vector dimension (text-embedding-3-small) |
| `LLM_MODEL` | — | `deepseek-chat` | Legacy model for disabled mind paths |
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
git clone https://github.com/dylmarriner/synapse-memory
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
├── app/                      # API, worker, search, memory, and agent runtime
├── docs/                     # Architecture and integration guides
├── integrations/             # MCP configs, plugins, skills, and manifests
├── migrations/               # Database migrations
├── scripts/                  # Deployment, bootstrap, and maintenance scripts
├── sdk/                      # Python and TypeScript SDKs
├── tests/                    # Integration and subsystem tests
└── docker-compose.yml        # Production deployment
```

## 📚 Documentation

- [Architecture Diagram](docs/architecture.html) — interactive SVG
- [Adopted Patterns](docs/adopted/README.md) — 19 distinctive memory ideas rewritten as Nexus-native modules
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
