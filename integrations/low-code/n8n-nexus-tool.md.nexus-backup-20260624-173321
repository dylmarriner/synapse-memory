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
