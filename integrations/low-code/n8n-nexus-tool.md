# n8n AI Agents + Nexus

Use HTTP Request nodes or an OpenAPI import.

```text
OpenAPI: {NEXUS_URL}/.well-known/nexus/openapi.json
Header:  Authorization: Bearer ${NEXUS_SECRET}
```

Common workflow:

1. Trigger receives user/task input.
2. HTTP Request: `POST /v1/memory/recall`.
3. Agent node uses returned memories.
4. HTTP Request: `POST /v1/memory/save` for durable outcomes.

# Nexus + RTK Agent Instructions

Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: n8n

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `/home/macuntu/Documents/synapse-memory/scripts/nexus-rtk <command>` for noisy shell commands when possible;
fall back to `rtk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries/lessons only.
