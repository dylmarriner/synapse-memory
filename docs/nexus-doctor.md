# Nexus Doctor

`scripts/nexus-doctor` scans the computer for AI agents and IDEs that Nexus can
connect to, checks local Nexus health, and can automatically write supported
configuration files.

For multi-computer setup, install Tailscale on the Nexus host and every agent
computer, then run Nexus Doctor on each agent computer with the host's Tailscale
URL. See [`agent-connection-tailscale.md`](agent-connection-tailscale.md).

Default mode is safe and read-only:

```bash
scripts/nexus-doctor
```

Apply changes:

```bash
scripts/nexus-doctor --apply
```

Every edited file is backed up beside the original:

```text
config.json.nexus-backup-YYYYMMDD-HHMMSS
```

## What it checks

- Nexus health at `/health`
- Obelisk installation via `obelisk doctor`
- Obelisk command-output optimization is available when the `obelisk` binary is on PATH

## What it can connect

### Already implemented

- Claude Desktop
- Claude Code instruction file
- Cline standalone
- Cline inside Windsurf / Antigravity / Trae
- Kade/Kilo MCP configs inside Windsurf / Antigravity / Trae
- Windsurf global MCP config
- Antigravity global MCP config
- VS Code MCP config
- Cursor MCP config
- OpenCode config
- Paperclip AI Nexus config
- Hermes env bootstrap
- OpenClaw env bootstrap
- Devin CLI instruction file
- Gemini CLI (`~/.gemini/settings.json`)
- Qwen Code (`~/.qwen/settings.json`, Gemini-compatible format)
- Codex CLI instructions (`~/.codex/NEXUS.md`)
- Aider instructions (`~/.aider/NEXUS.md`)
- Goose env bootstrap (`~/.goose/nexus.env`)
- OpenHands env bootstrap (`~/.openhands/nexus.env`)
- SWE-agent env bootstrap (`~/.swe-agent/nexus.env`)
- Roo Code globalStorage (VS Code/Windsurf/Trae/Antigravity families)
- Kilo Code standalone globalStorage
- Project instruction files: `GEMINI.md`, `QWEN.md`

### Still pending (see agent-target-registry.md)

Continue, Zed, CrewAI, LangGraph, AutoGen, PearAI, Amp, Augment Code, and
JetBrains AI Assistant. Low-code OpenAPI templates exist for Dify, Flowise,
Langflow, n8n, OpenWebUI, LibreChat, and AnythingLLM.

Full target list and integration backlog in `docs/agent-target-registry.md`.

## Configuration sources

The doctor reads `NEXUS_URL` and `NEXUS_SECRET` from environment variables first,
then from `.env` in this repository.

Override explicitly:

```bash
scripts/nexus-doctor --apply \
  --nexus-url http://100.93.75.87:7777 \
  --secret "$NEXUS_SECRET"
```

## Safety

- No writes unless `--apply` is provided.
- All writes are backed up.
- JSON configs are merged instead of replaced.
- Raw command output is not stored; Obelisk telemetry goes through the Obelisk
  command path and the durable memory tools.
