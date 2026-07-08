# Langflow + Nexus

Add Nexus as an API/request component:

```text
Base URL: {NEXUS_URL}
OpenAPI:  {NEXUS_URL}/.well-known/nexus/openapi.json
Header:   Authorization: Bearer ${NEXUS_SECRET}
```

Use recall before generation and save durable facts after important interactions.

# Nexus + Obelisk Agent Instructions

Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: langflow

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `/home/macuntu/Documents/synapse-memory/scripts/nexus-obelisk <command>` for noisy shell commands when possible;
fall back to `obelisk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries/lessons only.
