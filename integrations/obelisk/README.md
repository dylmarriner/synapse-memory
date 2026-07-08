# Obelisk Agent Integrations

Obelisk (`obelisk-ai/obelisk`) is a command-output token optimizer. It is not an MCP server
and it is not a memory database. Connect it to agents by making the agent prefer
`obelisk <command>` for noisy shell commands and, where supported, installing Obelisk's
native command-rewrite hook.

Verified on this machine:

```bash
obelisk --version
obelisk doctor
obelisk stats
```

Expected behavior: `obelisk doctor` and `obelisk stats` work. If they do not, the
wrong `obelisk` package may be installed.

## Universal policy for all agents

Use the Nexus Obelisk wrapper when Nexus credentials are configured. It runs Obelisk,
prints compact output, and records command telemetry in Nexus:

```bash
scripts/nexus-obelisk git status
scripts/nexus-obelisk pytest
```

Otherwise use Obelisk directly for commands that can dump lots of tokens:

```bash
obelisk run ls .
obelisk run cat path/to/file
obelisk run grep "pattern" .
obelisk run git status
obelisk run git diff
obelisk run git log -n 20
obelisk run pytest
obelisk run npm test
obelisk run pnpm test
obelisk run cargo test
obelisk run docker ps
obelisk run kubectl get pods
```

Use raw commands when exact unfiltered output is needed:

```bash
git log --oneline -20
cat exact-file.txt
```

## Claude Code / Claude Desktop

Best integration: Obelisk native Claude hook.

```bash
OBELISK_INIT_CLAUDE=1 bash scripts/setup-obelisk.sh
```

This installs/patches Claude Code hooks so shell commands are rewritten through
Obelisk automatically where Obelisk supports them.

Also add `integrations/obelisk/agent-instructions.md` to project or global Claude
instructions if your Claude environment does not load this repo's `CLAUDE.md`.

## Cline

Cline does not need an MCP entry for Obelisk. Keep Nexus MCP configured separately.

Recommended:

1. Ensure `obelisk` is on PATH for VS Code/Cline's shell:

   ```bash
   export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
   ```

2. Add `integrations/obelisk/agent-instructions.md` to Cline custom instructions.

3. Keep using Nexus MCP from `mcp/cline-mcp-settings.json` for
   durable memory.

## Devin CLI

Devin CLI integration is instruction/PATH based unless your Devin install exposes
a dedicated hook system.

Recommended shell bootstrap before launching Devin:

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
devin
```

Add `integrations/obelisk/agent-instructions.md` to Devin's repo instructions,
agent instructions, or equivalent project memory file.

Instruct Devin to prefix noisy commands with `obelisk run` and use raw commands
only when exact output is required.

## Hermes

Hermes should receive Obelisk as agent guidance plus PATH.

Recommended environment:

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
```

Use the Hermes Nexus plugin for memory and add `integrations/obelisk/agent-instructions.md`
to Hermes system instructions or plugin prompt guidance.

## OpenClaw

OpenClaw should receive Obelisk as prompt guidance plus PATH.

Recommended:

1. Ensure the OpenClaw runtime environment has:

   ```bash
   PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
   ```

2. Keep the Nexus OpenClaw plugin installed for memory.

3. Use `integrations/obelisk/agent-instructions.md` as OpenClaw system or plugin
   guidance.

## OpenCode

OpenCode integration is instruction/PATH based.

Recommended:

1. Ensure `obelisk` is on PATH in the shell that launches OpenCode.
2. Keep Nexus MCP configured from `integrations/mcp/opencode.json`.
3. Add `integrations/obelisk/agent-instructions.md` to OpenCode project/global
   instructions.

## One-command helper

Use:

```bash
bash scripts/connect-obelisk-agents.sh
```

It verifies Obelisk and writes ready-to-copy snippets under `integrations/obelisk/generated/`.

## Dashboard metrics

Nexus exposes Obelisk telemetry for the dashboard at:

```text
GET /v1/admin/obelisk
```

The endpoint reports total Obelisk command events, recent failures, top commands,
events by agent, durable memories created from Obelisk summaries, and estimated token
savings.
