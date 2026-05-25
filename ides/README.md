# Synapse IDE Extensions

MCP server configuration files for AI-native IDEs.

Each folder contains the `mcp_config.json` file needed to connect the IDE
to the Synapse Enterprise Memory server.

## Supported IDEs

| IDE | Config Path | Key |
|-----|-------------|-----|
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` |
| Antigravity | `~/.gemini/antigravity/mcp_config.json` | `mcpServers` |
| VS Code | `~/.vscode/mcp.json` | `servers` |

## Quick Install

```bash
node install-to-ides.mjs
```

This adds the `synapse` MCP server to all detected IDE configs.
For a single IDE:

```bash
node install-to-ides.mjs --windsurf
node install-to-ides.mjs --antigravity
node install-to-ides.mjs --vscode
```

## Manual Install

Copy the config from the relevant folder into your IDE's MCP config file.

## Server URL

```
http://100.91.55.113:8765/mcp
```

Available over Tailscale at `100.91.55.113` or locally at `127.0.0.1:8765`.

## MCP Server (Standalone)

The Synapse MCP server runs as a systemd user service:

```bash
systemctl --user status synapse-mcp
# → Active: running on port 8765
```

To run manually:

```bash
cd /home/lin/synapse-mcp
.venv/bin/python server.py
```

## Tools Available via MCP

`health`, `store`, `retrieve`, `update`, `delete`, `context`, `rank`,
`embed`, `compress`, `sync`, `list_memories`, `get_memory`, `get_tenant_info`
