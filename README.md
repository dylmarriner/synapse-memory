# Synapse Enterprise

Enterprise-grade, multi-tenant, cross-device AI memory and context orchestration
layer. Runs as an MCP server behind Tailscale, with native plugins for OpenClaw,
Hermes, Paperclip AI, and any MCP-compatible client.

```
/home/lin/synapse-mcp/
├── server.py                          # MCP server (15 tools, multi-tenant SQLite)
├── SYNAPSE-ENTERPRISE-BLUEPRINT.md    # Full architecture document (13 sections)
├── systemd/                           # Service files
│   └── synapse-mcp.service
├── scripts/                           # Install/build helpers
│   └── install.sh
├── sdk/
│   ├── python/                        # Python SDK (pip-installable)
│   │   └── synapse_sdk/__init__.py
│   └── typescript/                    # TypeScript SDK (npm package)
│       └── src/index.ts
├── plugins/
│   └── openclaw-synapse/              # Standalone OpenClaw plugin package
│       ├── package.json
│       ├── openclaw.plugin.json
│       ├── src/index.ts               # All-in-one plugin (9 tools + agent guidance)
│       ├── skills/synapse/SKILL.md
│       └── scripts/install-to-openclaw.mjs
├── client-configs/                    # Client configurations
│   ├── README.md
│   └── paperclip.json
└── .venv/                             # Python virtual environment
```

## Quick Start

```bash
# Install dependencies
cd /home/lin/synapse-mcp
python3 -m venv .venv
.venv/bin/pip install mcp numpy ulid-py zstandard cryptography PyJWT

# Install Python SDK
.venv/bin/pip install -e sdk/python

# Run server
.venv/bin/python server.py
# → http://localhost:8765/mcp (or http://100.91.55.113:8765/mcp over Tailscale)
```

## Systemd Service

```bash
systemctl --user daemon-reload
systemctl --user restart synapse-mcp
journalctl --user -u synapse-mcp -f
```

## OpenClaw Plugin

The plugin at `plugins/openclaw-synapse/` is a standalone package you can
install into any OpenClaw installation:

```bash
# Option 1: Copy into OpenClaw extensions/
cp -r plugins/openclaw-synapse /path/to/openclaw/extensions/synapse

# Option 2: Use the install script
OPENCLAW_ROOT=/path/to/openclaw node plugins/openclaw-synapse/scripts/install-to-openclaw.mjs
```

Then enable in OpenClaw config:
```yaml
plugins:
  synapse:
    enabled: true
    config:
      serverUrl: "http://100.91.55.113:8765/mcp"
```

## Python SDK Usage

```python
from synapse_sdk import SynapseClient

client = SynapseClient(api_key="syn_...")

# Store knowledge
client.store(kind="semantic", content="Auth uses JWT RS256 rotation",
             tags=["auth", "jwt"], importance=0.9)

# Retrieve before any task
ctx = client.context(query="authentication")
print(f"Tokens saved: {ctx['tokens_saved']}")

# Lifecycle hooks
client.on("memory.store", print)
```

## MCP Tools (15)

`health`, `register_tenant`, `register_device`, `store`, `retrieve`,
`update`, `delete`, `sync`, `rank`, `embed`, `compress`, `context`,
`list_memories`, `get_memory`, `get_tenant_info`

## Architecture

```
Edge Layer (IDE agents, CLI tools)
    │ MCP (streamable-http)
    ▼
Synapse MCP Server (port 8765)
    ├── Multi-tenant SQLite (WAL)
    ├── FTS5 keyword search
    ├── 64-dim pseudo-embedding vector search
    ├── Event-sourced sync log
    └── SOC2-ready audit trail
    │
    ▼ Tailscale (100.91.55.113)
Mesh sync with other nodes (Phase 1+)
```
