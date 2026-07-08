# Flowise + Nexus

Use an HTTP Request tool or OpenAPI tool against Nexus:

```text
OpenAPI: {NEXUS_URL}/.well-known/nexus/openapi.json
Header:  Authorization: Bearer ${NEXUS_SECRET}
```

Recommended flow:

1. Recall relevant memory with `POST /v1/memory/recall`.
2. Use retrieved context in the agent prompt.
3. Save durable lessons with `POST /v1/memory/save`.

# Nexus + Obelisk Agent Instructions

Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: flowise

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `/home/macuntu/Documents/synapse-memory/scripts/nexus-obelisk <command>` for noisy shell commands when possible;
fall back to `obelisk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries/lessons only.
