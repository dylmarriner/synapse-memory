# OpenWebUI + Nexus

If your OpenWebUI version supports OpenAPI tools/functions, import:

```text
{NEXUS_URL}/.well-known/nexus/openapi.json
```

Set:

```text
Authorization: Bearer ${NEXUS_SECRET}
```

Expose recall/reflect/save as model tools for persistent cross-chat memory.

# Nexus + RTK Agent Instructions

Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: openwebui

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `/home/macuntu/Documents/synapse-memory/scripts/nexus-rtk <command>` for noisy shell commands when possible;
fall back to `rtk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries/lessons only.
