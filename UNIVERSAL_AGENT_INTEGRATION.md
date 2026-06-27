# Nexus Universal Agent Integration

Nexus is now usable by any AI agent that can call **MCP**, **OpenAPI**, **REST**, **plugins**, or **skills/instructions**.

For cross-computer setup through Tailscale, see
[`docs/agent-connection-tailscale.md`](docs/agent-connection-tailscale.md).

## 🚀 One-command install — every agent

The fastest way to wire Nexus into any AI agent on this machine is the
universal installer. It auto-detects what's installed and uses each
agent's native install path with a config-file fallback.

```bash
# From the repo
scripts/nexus-install

# One-liner (no clone required)
curl -fsSL https://raw.githubusercontent.com/dylanmarriner/shared-memory-mcp/main/scripts/nexus-install-remote.sh \
  | NEXUS_URL=http://<host>:7777 NEXUS_SECRET=<secret> bash

# Show what's supported + detection status
scripts/nexus-install --list

# Install into specific agents
scripts/nexus-install paperclip opencode openclaw hermes

# Install into every supported agent (skip detection)
scripts/nexus-install --all

# Also install skills + hooks
scripts/nexus-install --with-skills --with-hooks

# Write rules to project (cwd) instead of $HOME
scripts/nexus-install --local

# Connection only (skip rules)
scripts/nexus-install --no-rules

# Dry-run (show what would happen)
scripts/nexus-install --dry-run
```

By default the installer writes three things per agent:

1. **Connection** — MCP server entry / plugin registration / config so the
   agent can actually call Nexus tools. Always installed.
2. **Rules** — global instruction files (`~/.claude/CLAUDE.md`,
   `~/.gemini/GEMINI.md`, `~/.codex/AGENTS.md`, `~/.aider/CONVENTIONS.md`,
   `~/.continue/NEXUS.md`, `~/.zed/AGENTS.md`, etc.) that teach the agent
   *when* to use Nexus. Installed by default. Use `--no-rules` to skip or
   `--local` to write project-level instead.
3. **Skills** — opt-in (`--with-skills`). A reusable `nexus-memory` skill
   installed to `~/.claude/skills/`, `~/.config/opencode/skills/`, and
   `~/.continue/config.yaml` so the LLM can discover and invoke it.
4. **Hooks** — opt-in (`--with-hooks`). Claude Code event hooks
   (SessionStart, UserPromptSubmit, Stop) in `~/.claude/settings.json` for
   auto-recall before each prompt and auto-save after each turn.

Canonical sources:
[`integrations/rules/nexus-memory.md`](integrations/rules/nexus-memory.md)
and
[`integrations/skills/nexus-memory/SKILL.md`](integrations/skills/nexus-memory/SKILL.md).

Supports 28+ agents including Paperclip, OpenClaw, OpenCode, Claude Code,
Hermes, Claude Desktop, Cline (standalone + inside any VS Code-compatible
IDE), Cursor, VS Code, VSCodium, Windsurf, Antigravity, Trae, PearAI,
Gemini CLI, Qwen Code, Codex CLI, Aider, Devin CLI, Goose, OpenHands,
SWE-agent, Continue, Zed, Amp, GitHub Copilot.

See [`integrations/plugins/install-registry.json`](integrations/plugins/install-registry.json)
for the full install registry (URLs, commands, config paths per agent).

## Endpoints

- Dashboard: `http://100.93.75.87:7777/`
- Health: `http://100.93.75.87:7777/health`
- HTTP MCP: `http://100.93.75.87:7777/mcp`
- MCP SSE: `http://100.93.75.87:7777/mcp/sse`
- OpenAPI: `http://100.93.75.87:7777/.well-known/nexus/openapi.json`
- Universal plugin manifest: `http://100.93.75.87:7777/.well-known/nexus/plugin-manifest.json`
- Install registry: `http://100.93.75.87:7777/.well-known/nexus/install-registry.json`
- REST base: `http://100.93.75.87:7777/v1`

All protected endpoints use:

```http
Authorization: Bearer <NEXUS_SECRET>
```

## Best integration path by agent type

| Agent type | Use this |
|---|---|
| **Any agent (auto-detect)** | `scripts/nexus-install` |
| **One-liner (no clone)** | `curl .../nexus-install-remote.sh \| bash` |
| Paperclip AI | `paperclip-plugin/` (auto-installed by installer) |
| OpenClaw | `openclaw-integration/extensions/nexus-memory/` (auto-installed) |
| OpenCode | `opencode plugin @nexus/memory --global` (auto-installed) |
| Claude Code | `claude plugin install integrations/plugins/claude-code` |
| Hermes | `integrations/plugins/hermes-nexus/` (auto-installed) |
| Cline | `integrations/mcp/cline-mcp-settings.json` |
| OpenCode (manual MCP) | `integrations/mcp/opencode.json` |
| Claude Desktop / stdio MCP clients | `integrations/mcp/claude-desktop.json` |
| OpenHands / OpenHuman / web agents | OpenAPI spec or REST endpoints |
| Anything prompt/skill based | `integrations/skills/nexus-memory-skill.md` |
| Anything plugin-manifest based | `integrations/plugins/universal-agent-plugin.manifest.json` |

## Auto-connect supported local agents

Use Nexus Doctor on each computer that runs agents:

```bash
scripts/nexus-doctor --nexus-url http://100.93.75.87:7777
scripts/nexus-doctor --apply --nexus-url http://100.93.75.87:7777 --secret "$NEXUS_SECRET"
```

It writes supported MCP, env, and instruction configs with backups. See
[`docs/nexus-doctor.md`](docs/nexus-doctor.md) for the current target list.

## MCP stdio bridge

Many tools cannot connect directly to HTTP MCP and require a local stdio process. Use:

```bash
python3 /path/to/synapse-memory/scripts/adapters/nexus_mcp_stdio.py
```

Environment variables:

```bash
export NEXUS_URL=http://100.93.75.87:7777
export NEXUS_SECRET=<secret>
export NEXUS_AGENT_ID=cline:kubuntu:project-name
export NEXUS_DEVICE=$(hostname)
export NEXUS_SOURCE=cline
```

## Recommended metadata for every save

```json
{
  "device": "device-name",
  "hostname": "host-name",
  "source": "cline|opencode|openhands|openhuman|paperclip|openclaw|custom",
  "model": "model-name",
  "workspace": "/absolute/project/path",
  "capabilities": ["coding", "terminal", "browser"]
}
```

This powers the dashboard's Agent Registry device/source view.

## Tool behavior

- `memory_recall`: run before substantive work.
- `memory_save`: save durable project facts, decisions, preferences, and context.
- `memory_save_lesson`: save corrections or mistakes as high-priority lessons.
- `memory_save_global`: share knowledge with every agent.
- `agent_context`: load agent-specific context and handoff notes.
- `memory_reflect`: synthesize retrieved memory into insight.

## REST examples

Save:

```bash
curl -X POST http://100.93.75.87:7777/v1/memory/save \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id":"cline:kubuntu:nexus",
    "content":"Nexus dashboard uses inline FastAPI HTML in app/main.py.",
    "memory_type":"world",
    "importance":0.7,
    "tags":["nexus","dashboard"],
    "metadata":{"device":"workstation","source":"cline","workspace":"/path/to/synapse-memory"}
  }'
```

Recall:

```bash
curl -X POST http://100.93.75.87:7777/v1/memory/recall \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"cline:kubuntu:nexus","query":"Nexus dashboard UI","limit":5}'
```
