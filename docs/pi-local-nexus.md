# Full Nexus deployment on Raspberry Pi

This is the setup for running the entire Nexus memory server on a Raspberry Pi, with embeddings generated in-process by FastEmbed.

This is the right setup when the Pi is your memory box:

```text
coding agents on laptop/desktop
  ↓ REST/MCP over LAN or Tailscale
Nexus on Raspberry Pi
  ↓ local FastEmbed embeddings
PostgreSQL + pgvector on Raspberry Pi
```

No separate remote embedding service is required. The `scripts/pi-embedding-server.py` helper is only for the alternative design where Nexus runs somewhere else and calls a Pi over HTTP. If Nexus itself runs on the Pi, use `EMBEDDING_PROVIDER=local` and keep the machinery in one box like a sane person pretending software is manageable.

## Recommended Pi role

Use the Pi for:

- durable memory
- vector embeddings
- lexical/graph/temporal recall
- MCP/REST memory access
- agent handoffs
- project notes

Do not use the Pi for:

- full local coding LLMs
- Claude/Codex replacements
- giant repo embedding jobs every minute
- trying to be a GPU server with a tiny hat

## Recommended embedding model

Use:

```env
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMS=384
```

`BAAI/bge-small-en-v1.5` is also a valid 384-dimensional option, but MiniLM is the lowest-friction default for a Pi.

## Pi `.env`

Create `.env` from `.env.example`, then set:

```env
NEXUS_SECRET=replace-with-a-long-random-secret
NEXUS_PORT=7777
POSTGRES_PASSWORD=replace-with-a-db-password

# Local Pi embeddings
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMS=384
LOCAL_EMBEDDING_CACHE_DIR=/tmp/fe_cache

# Keep LLM features off on the Pi by default
LLM_ENABLED=false
MIND_ENABLED=false
MIND_REFLECTION_ENABLED=false
LLM_QUERY_EXPANSION=false
RERANKER_ENABLED=false
USE_ACTIVE_MEMORY=false
```

## Run with the Pi compose file

```bash
docker compose -f docker-compose.pi.yml up -d --build
```

Check health:

```bash
curl http://localhost:7777/health
```

From another machine on Tailscale or LAN:

```bash
curl http://<pi-host>:7777/health
```

## First embedding warm-up

The first save may be slow because FastEmbed downloads and initializes the model. That is normal. It is the computer doing setup, not having a spiritual crisis, although the logs may imply otherwise.

Save a test memory:

```bash
export NEXUS_SECRET='replace-with-your-secret'

curl -s -X POST http://<pi-host>:7777/v1/memory/save \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"content":"Nexus is running on the Raspberry Pi with local MiniLM embeddings.","importance":0.8,"tags":["pi","embeddings"]}'
```

Recall it:

```bash
curl -s -X POST http://<pi-host>:7777/v1/memory/recall \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"query":"local Pi embeddings","limit":5,"search_modes":["vector","lexical"]}' \
  | jq '.results[] | {content, relevance, matched_by}'
```

## Client agents

On your laptop/desktop, point agents to the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/dylmarriner/synapse-memory/main/scripts/nexus-install-remote.sh \
  | NEXUS_URL=http://<pi-host>:7777 NEXUS_SECRET=<secret> bash
```

Use Tailscale if you want access away from home. Do not expose Nexus directly to the public internet. Bearer tokens are good; random internet goblins are persistent.

## Notes on dimensions

The database vector column uses `EMBEDDING_DIMS`. If you change from a 384-dimensional model to a different dimension, you need to rebuild the database column/reindex old memories. Mixing dimensions does not work.

Stay on 384 dimensions until the rest of the system is stable.

## Relationship to the HTTP embedding service

This repo also includes:

```text
scripts/pi-embedding-server.py
docs/pi-embedding-service.md
```

That is for the alternative layout:

```text
Nexus on desktop/server → Pi embedding service
```

Your intended layout is instead:

```text
Nexus + embeddings + Postgres + Redis all on Pi
```

So use this document and `docker-compose.pi.yml` first.
