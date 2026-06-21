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
