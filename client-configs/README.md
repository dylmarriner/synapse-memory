# Synapse Client Configurations

## Hermes Agent

Already configured in `/home/lin/.hermes/config.yaml`:
```yaml
mcp_servers:
  synapse:
    url: "http://100.91.55.113:8765/mcp"
    timeout: 120
    connect_timeout: 30
```

## OpenClaw

The Synapse plugin is available as a bundled extension at
`extensions/synapse/`. Enable it in OpenClaw config:
```yaml
plugins:
  synapse:
    enabled: true
    config:
      serverUrl: "http://100.91.55.113:8765/mcp"
      # apiKey: "syn_..."  # Required for multi-tenant mode
      defaultProjectKey: "default"
```

## Paperclip AI

Add to Paperclip MCP config (`paperclip.json`):
```json
{
  "mcpServers": {
    "synapse": {
      "url": "http://100.91.55.113:8765/mcp"
    }
  }
}
```

## Windsurf / Cursor / Antigravity / VS Code

```json
{
  "mcpServers": {
    "synapse": {
      "url": "http://100.91.55.113:8765/mcp"
    }
  }
}
```

## Claude Code CLI

```bash
claude mcp add --transport http synapse http://100.91.55.113:8765/mcp
```

## Local-only fallback

```
http://127.0.0.1:8765/mcp
```

## Tools available via MCP

| Tool | Description |
|---|---|
| `health` | Server status + stats |
| `register_tenant` | Create tenant, get API key |
| `register_device` | Register device identity |
| `store` | Store memory (working/episodic/semantic) |
| `retrieve` | Hybrid keyword + semantic search |
| `update` | Merge/overwrite/append |
| `delete` | Delete with sync tombstone |
| `sync` | Event-sourced delta sync |
| `rank` | Importance-based ranking |
| `embed` | Text embedding generation |
| `compress` | Deduplicate/summarize/prune |
| `context` | Optimized context pack |
| `list_memories` | Pagination |
| `get_memory` | Single memory by ID |
| `get_tenant_info` | Tenant usage stats |
