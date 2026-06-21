# Nexus Doctor

`scripts/nexus-doctor` scans the computer for AI agents and IDEs that Nexus can
connect to, checks local Nexus/RTK health, and can automatically write supported
configuration files.

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
- RTK installation via `rtk gain`
- `scripts/nexus-rtk` wrapper functionality

## What it can connect

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

See `docs/agent-target-registry.md` for the expanded registry of additional CLI
agents, IDEs, editor extensions, autonomous SWE agents, and local agent
frameworks that Nexus Doctor should support next.

High-priority next targets include Gemini CLI, Qwen Code, Codex CLI, Goose,
Continue, Aider, Roo Code, Kilo Code standalone, Zed, GitHub Copilot
instructions, OpenHands, SWE-agent, CrewAI, LangGraph, AutoGen, Dify, Flowise,
Langflow, OpenWebUI, LibreChat, and AnythingLLM.

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
- Raw command output is not stored; RTK telemetry goes through `scripts/nexus-rtk`
  and `/v1/rtk/events`.
