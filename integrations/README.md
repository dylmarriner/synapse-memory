# Nexus Integrations

This folder makes Nexus connectable to nearly any AI agent runtime.

## Files

```text
mcp/cline-mcp-settings.json        Cline MCP config example
mcp/opencode.json                  OpenCode MCP config example
mcp/claude-desktop.json            Claude/Desktop-compatible MCP config
openapi/nexus-memory.openapi.json  OpenAPI spec for agents that import APIs/plugins
plugins/universal-agent-plugin.manifest.json  Generic plugin manifest
skills/nexus-memory-skill.md       Prompt/skill instructions for agents without tools
```

## Stdio MCP command

Use this with agents that support MCP via local command:

```bash
python3 /media/kubuntux/DEVELOPMENT1/shared-memory/nexus/scripts/adapters/nexus_mcp_stdio.py
```

Recommended env:

```bash
NEXUS_URL=http://100.93.75.87:7777
NEXUS_SECRET=<secret>
NEXUS_AGENT_ID=<agent>:<device>:<workspace>
NEXUS_DEVICE=$(hostname)
NEXUS_SOURCE=<cline|opencode|openhuman|openhands|custom>
```

## HTTP MCP endpoint

Agents that support streamable/HTTP MCP can connect to:

```text
http://100.93.75.87:7777/mcp
```

Some clients need the SSE endpoint too:

```text
http://100.93.75.87:7777/mcp/sse
```

## RTK command-output optimization

Use Nexus for durable memory and RTK for compact shell-command output. RTK is a
CLI proxy/filter, not a memory database.

```bash
bash scripts/setup-rtk.sh
# Optional Claude hook patch:
RTK_INIT_CLAUDE=1 bash scripts/setup-rtk.sh
```

Agents should prefer:

```bash
rtk git status
rtk git diff
rtk grep "pattern" .
rtk pytest
```

See `docs/rtk-integration.md` for the full integration policy.

Per-agent RTK snippets are in `integrations/rtk/`. Generate local ready-to-copy
instructions with:

```bash
bash scripts/connect-rtk-agents.sh
```

Supported guidance targets: Cline, Claude, Devin CLI, Hermes, OpenClaw, OpenCode.

## Nexus Doctor auto-connect

Run a machine-wide scan for supported agents/IDEs and see what Nexus can connect:

```bash
scripts/nexus-doctor
```

Apply discovered connections with backups:

```bash
scripts/nexus-doctor --apply
```

Supported targets include Claude Desktop/Code, Cline, Windsurf, Antigravity,
Trae, VS Code, Cursor, Gemini CLI, Qwen Code, Codex CLI, Aider, OpenCode,
Paperclip AI, Goose, OpenHands, SWE-agent, Hermes, OpenClaw, Devin CLI, and
project instruction files where discoverable.

Additional targets can be added declaratively in:

```text
integrations/doctor/targets.json
```

Low-code/OpenAPI import templates are in:

```text
integrations/low-code/
```

## OpenAPI/plugin endpoint

```text
http://100.93.75.87:7777/.well-known/nexus/openapi.json
http://100.93.75.87:7777/.well-known/nexus/plugin-manifest.json
```

## Cline

Copy `mcp/cline-mcp-settings.json` into Cline MCP settings and replace `${NEXUS_SECRET}`.

## OpenCode

Merge `mcp/opencode.json` into your OpenCode config and replace `${NEXUS_SECRET}`.

## OpenHuman / OpenHands / generic web agents

Use the OpenAPI URL if supported. Otherwise add `skills/nexus-memory-skill.md` to the agent instructions and expose REST/MCP tools as custom actions.
