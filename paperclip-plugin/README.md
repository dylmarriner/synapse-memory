# Nexus Memory for Paperclip AI

Paperclip plugin that connects Paperclip-managed agents to the Nexus unified memory server.

## What it adds

Agent tools:

- `nexus_recall` — search Nexus memory with vector, lexical, graph, and temporal recall.
- `nexus_save` — save durable Paperclip lessons, decisions, preferences, project/issue context, and run summaries.
- `nexus_reflect` — ask Nexus to synthesize relevant memory for planning/debugging/handoffs.
- `nexus_status` — verify Paperclip can reach Nexus.

Scoped plugin API routes:

- `GET /api/plugins/nexus-memory/api/health?companyId=<id>`
- `POST /api/plugins/nexus-memory/api/recall`
- `POST /api/plugins/nexus-memory/api/save`
- `POST /api/plugins/nexus-memory/api/reflect`

## Install locally into Paperclip

```bash
curl -X POST http://127.0.0.1:3100/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"packageName":"/media/kubuntux/DEVELOPMENT1/shared-memory/nexus/paperclip-plugin","isLocalPath":true}'
```

Then configure plugin settings:

- `nexusUrl`: `http://100.93.75.87:7777`
- `nexusSecret`: Nexus bearer secret, or use `nexusSecretRef` if your Paperclip secret provider is configured.
- `agentIdPrefix`: default `paperclip`
- `defaultLimit`: default `8`

## Build/test

```bash
npm install
npm run typecheck
npm test
npm run build
```
