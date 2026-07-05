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
