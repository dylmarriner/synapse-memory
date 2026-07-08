# Low-code / Agent Builder Integrations

Nexus exposes a REST API and OpenAPI document that low-code agent builders can
import as an HTTP/OpenAPI tool.

Useful endpoints:

```text
GET  {NEXUS_URL}/.well-known/nexus/openapi.json
GET  {NEXUS_URL}/.well-known/nexus/plugin-manifest.json
POST {NEXUS_URL}/v1/memory/save
POST {NEXUS_URL}/v1/memory/recall
POST {NEXUS_URL}/v1/memory/reflect
GET  {NEXUS_URL}/v1/agents/{agent_id}/context
POST {NEXUS_URL}/v1/obelisk/events
```

Auth header:

```text
Authorization: Bearer ${NEXUS_SECRET}
```

Templates in this directory are written by Nexus Doctor and can be imported or
copied into Dify, Flowise, Langflow, n8n, OpenWebUI, LibreChat, and AnythingLLM.
