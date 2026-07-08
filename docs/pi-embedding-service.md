# Raspberry Pi embedding service

Nexus can now use a remote HTTP embedding provider. This is intended for a Raspberry Pi, mini PC, or spare LAN box that runs a small FastEmbed model and returns vectors to Nexus.

This is useful when you want free semantic memory recall without running a full coding LLM locally. The Pi does one boring job: turn saved memories and recall queries into vectors. Boring, therefore useful.

## Recommended model

Start with:

```text
sentence-transformers/all-MiniLM-L6-v2
```

It returns 384-dimensional vectors, so keep:

```env
EMBEDDING_DIMS=384
```

You can also use:

```text
BAAI/bge-small-en-v1.5
```

Also 384-dimensional. Do not switch to a different dimension without updating `EMBEDDING_DIMS` and rebuilding/reindexing the vector column. pgvector is not a mind reader, despite the branding situation getting out of hand.

## Pi setup

On the Pi:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip

cd ~/synapse-memory
python3 -m venv .venv
. .venv/bin/activate
pip install fastapi uvicorn fastembed
```

Run the service:

```bash
python scripts/pi-embedding-server.py \
  --host 0.0.0.0 \
  --port 8787 \
  --model sentence-transformers/all-MiniLM-L6-v2
```

Check it:

```bash
curl http://<pi-host>:8787/health
```

Embed a test sentence:

```bash
curl -s -X POST http://<pi-host>:8787/embed \
  -H 'Content-Type: application/json' \
  -d '{"texts":["Nexus uses Obelisk for token control and Synapse for durable memory."]}' \
  | jq '.dim'
```

Expected:

```text
384
```

## Optional service token

On the Pi:

```bash
export EMBEDDING_API_KEY='change-me-embedding-token'
python scripts/pi-embedding-server.py --host 0.0.0.0 --port 8787
```

Then Nexus must send the same token:

```env
EMBEDDING_API_KEY=change-me-embedding-token
```

## Nexus configuration

In the Nexus `.env`:

```env
EMBEDDING_PROVIDER=http
EMBEDDING_BASE_URL=http://<pi-host>:8787/embed
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMS=384
EMBEDDING_TIMEOUT_SECONDS=10
```

Restart Nexus:

```bash
docker compose up -d --build
```

Save a memory:

```bash
curl -s -X POST http://localhost:7777/v1/memory/save \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"content":"The Obelisk Claude hook must fire before Bash commands.","importance":0.8,"tags":["obelisk","claude"]}'
```

Recall it:

```bash
curl -s -X POST http://localhost:7777/v1/memory/recall \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"query":"Claude hook before Bash","limit":5,"search_modes":["vector","lexical"]}' \
  | jq '.results[] | {content, relevance, matched_by}'
```

## Provider modes

```env
EMBEDDING_PROVIDER=auto
```

Order:

1. HTTP provider, if `EMBEDDING_BASE_URL` is set
2. OpenAI-compatible embeddings, if `OPENAI_API_KEY` is set
3. Local FastEmbed fallback

```env
EMBEDDING_PROVIDER=http
```

Only use the remote HTTP service.

```env
EMBEDDING_PROVIDER=local
```

Only use in-process FastEmbed inside Nexus.

```env
EMBEDDING_PROVIDER=disabled
```

Skip vector embeddings entirely. Lexical, graph, and temporal recall still work.

## Notes

- Keep the embedding model dimension aligned with `EMBEDDING_DIMS`.
- Do not expose the Pi service to the public internet. Use LAN or Tailscale.
- Embeddings are for memory recall. Use a code indexer for source-code symbols and references.
- If you change models or dimensions, old vectors should be regenerated. Otherwise recall quality becomes a soup, and not even a good soup.
