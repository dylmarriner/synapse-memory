# Dify + Nexus

Create a custom tool or OpenAPI tool using:

```text
{NEXUS_URL}/.well-known/nexus/openapi.json
```

Set auth header:

```text
Authorization: Bearer ${NEXUS_SECRET}
```

Recommended tools to expose:

- `memory_save` for durable facts, preferences, lessons, decisions.
- `memory_recall` before answering user/project-specific questions.
- `memory_reflect` for synthesis and planning.

# Nexus + RTK Agent Instructions

Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: dify

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `/home/macuntu/Documents/synapse-memory/scripts/nexus-rtk <command>` for noisy shell commands when possible;
fall back to `rtk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries/lessons only.
