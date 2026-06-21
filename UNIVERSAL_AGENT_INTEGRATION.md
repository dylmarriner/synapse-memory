# Nexus Universal Agent Integration

Nexus is now usable by any AI agent that can call **MCP**, **OpenAPI**, **REST**, **plugins**, or **skills/instructions**.

## Endpoints

- Dashboard: `http://100.93.75.87:7777/`
- Health: `http://100.93.75.87:7777/health`
- HTTP MCP: `http://100.93.75.87:7777/mcp`
- MCP SSE: `http://100.93.75.87:7777/mcp/sse`
- OpenAPI: `http://100.93.75.87:7777/.well-known/nexus/openapi.json`
- Universal plugin manifest: `http://100.93.75.87:7777/.well-known/nexus/plugin-manifest.json`
- REST base: `http://100.93.75.87:7777/v1`

All protected endpoints use:

```http
Authorization: Bearer <NEXUS_SECRET>
```

## Best integration path by agent type

| Agent type | Use this |
|---|---|
| Cline | `integrations/mcp/cline-mcp-settings.json` |
| OpenCode | `integrations/mcp/opencode.json` |
| Claude Desktop / stdio MCP clients | `integrations/mcp/claude-desktop.json` |
| OpenHands / OpenHuman / web agents | OpenAPI spec or REST endpoints |
| Paperclip AI | `paperclip-plugin/` |
| OpenClaw | `openclaw-plugin/` |
| Anything prompt/skill based | `integrations/skills/nexus-memory-skill.md` |
| Anything plugin-manifest based | `integrations/plugins/universal-agent-plugin.manifest.json` |

## MCP stdio bridge

Many tools cannot connect directly to HTTP MCP and require a local stdio process. Use:

```bash
python3 /media/kubuntux/DEVELOPMENT1/shared-memory/nexus/scripts/adapters/nexus_mcp_stdio.py
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
    "metadata":{"device":"kubuntux","source":"cline","workspace":"/media/kubuntux/DEVELOPMENT1/shared-memory/nexus"}
  }'
```

Recall:

```bash
curl -X POST http://100.93.75.87:7777/v1/memory/recall \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"cline:kubuntu:nexus","query":"Nexus dashboard UI","limit":5}'
```
