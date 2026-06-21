# RTK Agent Integrations

RTK (`rtk-ai/rtk`) is a command-output token optimizer. It is not an MCP server
and it is not a memory database. Connect it to agents by making the agent prefer
`rtk <command>` for noisy shell commands and, where supported, installing RTK's
native command-rewrite hook.

Verified on this machine:

```bash
rtk --version
rtk gain
```

Expected behavior: `rtk gain` works. If it does not, the wrong `rtk` package may
be installed.

## Universal policy for all agents

Use the Nexus RTK wrapper when Nexus credentials are configured. It runs RTK,
prints compact output, and records command telemetry in Nexus:

```bash
scripts/nexus-rtk git status
scripts/nexus-rtk pytest
```

Otherwise use RTK directly for commands that can dump lots of tokens:

```bash
rtk ls .
rtk read path/to/file
rtk grep "pattern" .
rtk git status
rtk git diff
rtk git log -n 20
rtk pytest
rtk npm test
rtk pnpm test
rtk cargo test
rtk docker ps
rtk kubectl get pods
```

Use raw commands or `rtk proxy <command>` when exact unfiltered output is needed:

```bash
rtk proxy git log --oneline -20
rtk proxy cat exact-file.txt
```

## Claude Code / Claude Desktop

Best integration: RTK native Claude hook.

```bash
RTK_INIT_CLAUDE=1 bash scripts/setup-rtk.sh
rtk init --show
```

This installs/patches Claude Code hooks so shell commands are rewritten through
RTK automatically where RTK supports them.

Also add `integrations/rtk/agent-instructions.md` to project or global Claude
instructions if your Claude environment does not load this repo's `CLAUDE.md`.

## Cline

Cline does not need an MCP entry for RTK. Keep Nexus MCP configured separately.

Recommended:

1. Ensure `rtk` is on PATH for VS Code/Cline's shell:

   ```bash
   export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
   ```

2. Add `integrations/rtk/agent-instructions.md` to Cline custom instructions.

3. Keep using Nexus MCP from `integrations/mcp/cline-mcp-settings.json` for
   durable memory.

## Devin CLI

Devin CLI integration is instruction/PATH based unless your Devin install exposes
a dedicated hook system.

Recommended shell bootstrap before launching Devin:

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export RTK_TELEMETRY_DISABLED=1
devin
```

Add `integrations/rtk/agent-instructions.md` to Devin's repo instructions,
agent instructions, or equivalent project memory file.

If Devin CLI supports a command wrapper in your installation, set it to:

```bash
rtk proxy
```

for commands where exact output is desired, or instruct Devin to prefix noisy
commands with `rtk`.

## Hermes

Hermes should receive RTK as agent guidance plus PATH.

Recommended environment:

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export RTK_TELEMETRY_DISABLED=1
```

Use the Hermes Nexus plugin for memory and add `integrations/rtk/agent-instructions.md`
to Hermes system instructions or plugin prompt guidance.

## OpenClaw

OpenClaw should receive RTK as prompt guidance plus PATH.

Recommended:

1. Ensure the OpenClaw runtime environment has:

   ```bash
   PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
   RTK_TELEMETRY_DISABLED=1
   ```

2. Keep the Nexus OpenClaw plugin installed for memory.

3. Use `integrations/rtk/agent-instructions.md` as OpenClaw system or plugin
   guidance.

## OpenCode

OpenCode integration is instruction/PATH based.

Recommended:

1. Ensure `rtk` is on PATH in the shell that launches OpenCode.
2. Keep Nexus MCP configured from `integrations/mcp/opencode.json`.
3. Add `integrations/rtk/agent-instructions.md` to OpenCode project/global
   instructions.

## One-command helper

Use:

```bash
bash scripts/connect-rtk-agents.sh
```

It verifies RTK and writes ready-to-copy snippets under `integrations/rtk/generated/`.

## Dashboard metrics

Nexus exposes RTK telemetry for the future dashboard at:

```text
GET /v1/admin/rtk
```

The endpoint reports total RTK command events, recent failures, top commands,
events by agent, durable memories created from RTK summaries, and estimated token
savings.
