# Connecting agents across computers with Tailscale

This guide explains how to connect AI agents and IDEs to one shared Nexus memory
server, whether they run on the Nexus host or on another computer over
Tailscale.

## Network model

Run Nexus once on a trusted machine, then point every agent at that machine:

```text
Agent computer -> Tailscale tailnet -> Nexus host:7777 -> PostgreSQL/Redis
```

Nexus exposes:

| Service | URL |
|---|---|
| Dashboard | `http://<nexus-host>:7777/` |
| Health check | `http://<nexus-host>:7777/health` |
| REST API | `http://<nexus-host>:7777/v1` |
| HTTP MCP | `http://<nexus-host>:7777/mcp` |
| SSE MCP | `http://<nexus-host>:7777/mcp/sse` |
| OpenAPI | `http://<nexus-host>:7777/.well-known/nexus/openapi.json` |

Use the Tailscale IP or MagicDNS name for `<nexus-host>`, for example
`100.93.75.87` or `nexus-server.tailnet-name.ts.net`.

## 1. Start Nexus on the host computer

On the computer that owns the Nexus data:

```bash
cd /path/to/synapse-memory
cp .env.example .env
# Edit .env and set NEXUS_SECRET plus model/API keys.
docker compose up -d
curl http://localhost:7777/health
```

The API process must listen on all interfaces, not only `127.0.0.1`. The
provided Docker Compose setup publishes port `7777`; for standalone Uvicorn use:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 7777
```

## 2. Put the host on Tailscale

Install and sign in to Tailscale on the Nexus host:

```bash
tailscale up
tailscale ip -4
```

Record the IPv4 address. In the examples below this guide uses:

```text
http://100.93.75.87:7777
```

From another Tailscale device, verify access:

```bash
curl http://100.93.75.87:7777/health
```

If that fails, check that the Nexus host is online in Tailscale, port `7777` is
published, and local firewall rules allow connections from the Tailscale
interface.

## 3. Export client environment variables

On every computer that runs agents:

```bash
export NEXUS_URL=http://100.93.75.87:7777
export NEXUS_SECRET=<same-secret-from-the-host-env>
export NEXUS_DEVICE=$(hostname)
```

Use stable agent IDs so memories are easy to audit:

```text
<agent>:<device>:<workspace>
```

Examples:

```text
codex:macbook:synapse-memory
cline:workstation:mobile-app
opencode:linuxbox:infra
```

## 4. Auto-connect local agents with Nexus Doctor

When the agent computer has this repository checked out, use Nexus Doctor:

```bash
cd /path/to/synapse-memory
scripts/nexus-doctor --nexus-url "$NEXUS_URL"
scripts/nexus-doctor --apply --nexus-url "$NEXUS_URL" --secret "$NEXUS_SECRET"
```

The first command is a dry run. The second writes supported local configs and
creates backups beside edited files.

Nexus Doctor can configure many local targets, including Claude Desktop/Code,
Cline, Windsurf, Antigravity, Trae, VS Code, Cursor, Gemini CLI, Qwen Code,
Codex CLI, Aider, OpenCode, Paperclip, Goose, Hermes, OpenClaw, Devin CLI,
OpenHands, SWE-agent, Roo Code, Kilo Code, VSCodium, PearAI, and project
instruction files where discoverable.

## 5. Connect agents manually

Use manual setup when Nexus Doctor does not support the agent, the agent runs on
a machine without this repository, or the client has a custom config location.

### Agents with HTTP MCP

Use this config shape when the agent can connect to MCP over HTTP:

```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://100.93.75.87:7777/mcp",
      "headers": {
        "Authorization": "Bearer <NEXUS_SECRET>"
      }
    }
  }
}
```

Some clients call the top-level key `servers` instead of `mcpServers`; keep the
server body the same.

### Agents with stdio MCP only

Some agents require a local command instead of a remote MCP URL. Use the stdio
bridge on the agent computer:

```json
{
  "mcpServers": {
    "nexus": {
      "command": "python3",
      "args": ["/path/to/synapse-memory/scripts/adapters/nexus_mcp_stdio.py"],
      "env": {
        "NEXUS_URL": "http://100.93.75.87:7777",
        "NEXUS_SECRET": "<NEXUS_SECRET>",
        "NEXUS_AGENT_ID": "agent:device:workspace"
      }
    }
  }
}
```

The bridge translates local stdio MCP calls into Nexus HTTP MCP calls over
Tailscale.

### Agents with REST or OpenAPI tools

Use the OpenAPI URL:

```text
http://100.93.75.87:7777/.well-known/nexus/openapi.json
```

Set the auth header on every protected request:

```http
Authorization: Bearer <NEXUS_SECRET>
```

REST base URL:

```text
http://100.93.75.87:7777/v1
```

### Agents with instructions only

Add this to the agent's project or global instructions:

```markdown
Nexus is available for durable memory.

- REST: http://100.93.75.87:7777/v1
- MCP: http://100.93.75.87:7777/mcp
- Agent ID: <agent>:<device>:<workspace>

Use Nexus for durable preferences, lessons, fixes, decisions, and handoffs.
Use `obelisk <command>` for noisy shell commands when possible. Do not store
raw command noise as memory; save durable summaries and lessons only.
```

## Agent-by-agent connection matrix

| Agent / IDE | Best method | Notes |
|---|---|---|
| Claude Desktop | stdio MCP | Use the local bridge in `scripts/adapters/nexus_mcp_stdio.py`. |
| Claude Code | instructions + Obelisk optimization | Add Nexus instructions and use Obelisk for noisy shell commands. |
| Cline | HTTP MCP or stdio MCP | VS Code-like installs often accept HTTP MCP; standalone Cline can use stdio. |
| Roo Code / Kilo Code / Kade | HTTP MCP | Usually use VS Code-compatible MCP settings. |
| Windsurf / Antigravity / Trae | HTTP MCP | Nexus Doctor scans their global storage and global MCP config paths. |
| VS Code / VSCodium / Cursor / PearAI | HTTP MCP | Use the editor MCP config plus project instructions for behavior. |
| Gemini CLI / Qwen Code | HTTP MCP | Nexus Doctor writes `settings.json` in their standard config directories. |
| Codex CLI / Aider / Devin CLI | instructions | Use project or global instruction files and REST/OpenAPI if available. |
| OpenCode | stdio MCP | Use the bridge command in OpenCode's `mcp` config. |
| Paperclip | plugin/config | Use `paperclip-plugin/` or Nexus Doctor's Paperclip config. |
| Hermes | HTTP MCP + env/hooks | Nexus Doctor configures MCP, user context, and a session hook. |
| OpenClaw | env/bootstrap + plugin | Use the OpenClaw Nexus plugin or env bootstrap. |
| Goose / OpenHands / SWE-agent | env/bootstrap | Provide `NEXUS_URL`, `NEXUS_SECRET`, and instructions inside the runtime/container. |
| Dify / Flowise / Langflow / n8n / OpenWebUI / LibreChat / AnythingLLM | OpenAPI/REST | Import templates from `integrations/low-code/`. |
| Custom agents | HTTP MCP, stdio bridge, or REST | Prefer HTTP MCP when available; use REST for simple save/recall tools. |

## Verify an agent connection

Check health from the agent computer:

```bash
curl "$NEXUS_URL/health"
```

List MCP tools:

```bash
curl -s -X POST "$NEXUS_URL/mcp" \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}'
```

Save a test memory:

```bash
curl -s -X POST "$NEXUS_URL/v1/memory/save" \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "manual:test",
    "content": "Nexus Tailscale connection test succeeded.",
    "importance": 0.5,
    "tags": ["nexus", "tailscale", "test"]
  }'
```

Recall it:

```bash
curl -s -X POST "$NEXUS_URL/v1/memory/recall" \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"manual:test","query":"Tailscale connection test","limit":3}'
```

## Troubleshooting

| Problem | Check |
|---|---|
| `curl /health` fails from another computer | Confirm both devices are online in Tailscale, use `tailscale ping <host>`, and verify Nexus listens on `0.0.0.0:7777`. |
| `401 Unauthorized` | The client `NEXUS_SECRET` does not match the host. |
| MCP works locally but not remotely | Use the Tailscale IP/MagicDNS name, not `localhost`, in remote configs. |
| Stdio MCP command fails | Ensure the bridge file exists on the agent computer and Python can run it. |
| Agent saves are hard to identify | Set `NEXUS_AGENT_ID`, `NEXUS_DEVICE`, and `NEXUS_SOURCE` per agent. |
| Too much shell output enters context | Use `obelisk <command>` for noisy shell commands. |

## Security notes

- Treat `NEXUS_SECRET` like an API token.
- Prefer Tailscale private addresses over exposing port `7777` to the public
  internet.
- Use a different secret when rotating credentials; update every agent config
  after rotation.
- Do not store raw terminal output as memory. Save durable summaries, decisions,
  preferences, fixes, lessons, and handoffs.
