# RTK + Nexus Integration

Nexus is the durable memory layer. RTK is the command-output token optimizer.

Together they support the goal of remembering far more than single-agent memory
systems while keeping the active LLM context affordable:

- **Nexus remembers everything durable**: preferences, lessons, decisions,
  project facts, summaries, entities, contradictions, global shared knowledge,
  and cross-agent handoffs.
- **RTK reduces transient shell-output tokens** before they enter the model
  context: `git`, `ls`, `grep`/`rg`, `pytest`, `npm`/`pnpm`, `docker`,
  `kubectl`, `cargo`, and similar high-volume commands.

RTK does **not** replace Nexus, BrainSync, AgentMemory, Hindsight, or Honcho as a
memory store. It is a CLI proxy/filter. The right architecture is:

```text
Agent shell command → RTK proxy/filter → compact output to LLM
Agent facts/lessons/preferences → Nexus MCP/REST → PostgreSQL + pgvector + graph + temporal recall
```

Nexus also exposes an RTK event endpoint for agents/runtimes that support hooks
or command wrappers:

```text
POST /v1/rtk/events
```

Use it to record compact command telemetry and optionally save a durable lesson.
Do not use it to dump raw command output into memory by default.

## Why this is better than plain memory-only systems

Memory systems often fail because they either:

1. stuff too much history into every prompt, or
2. save too little to stay affordable.

Nexus + RTK separates those concerns:

- Store high-volume durable memory in Nexus.
- Retrieve only relevant context via fused vector/lexical/graph/temporal recall.
- Use RTK to prevent large command outputs from consuming the live context.
- Preserve full source-of-truth data in the database, while summaries/context packs
  are token-bounded views.

## Install RTK

First verify whether the correct RTK is already installed:

```bash
rtk --version
rtk gain
which rtk
```

`rtk gain` must work. If it does not, you may have the wrong `rtk` package.

Linux/macOS quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
rtk gain
```

Cargo install alternative:

```bash
cargo install --git https://github.com/rtk-ai/rtk
rtk gain
```

Disable telemetry if desired:

```bash
export RTK_TELEMETRY_DISABLED=1
rtk telemetry disable || true
```

## Claude Code / Claude-style hook setup

Recommended global hook setup:

```bash
rtk init -g --auto-patch
rtk init --show
```

Minimal hook-only setup:

```bash
rtk init -g --hook-only --auto-patch
rtk init --show
```

Project-local setup:

```bash
rtk init
```

## Agent command policy

Agents should prefer RTK for commands that generate noisy output:

```bash
rtk ls .
rtk read app/main.py
rtk grep "pattern" app
rtk git status
rtk git diff
rtk pytest
rtk npm test
rtk pnpm test
rtk docker ps
rtk kubectl get pods
```

Use raw commands or `rtk proxy` when full unfiltered output is required:

```bash
rtk proxy git log --oneline -20
rtk proxy cat exact-file.txt
```

## Nexus memory policy with RTK

RTK should never be used as an excuse to save less. It only reduces live command
tokens. Nexus should still save durable facts aggressively:

- user preferences
- corrections and lessons
- project architecture decisions
- exact commands that fixed an issue
- recurring errors and their fixes
- cross-agent handoff notes
- environment-specific gotchas
- stable repo conventions

Do **not** save ephemeral command output unless it contains a durable lesson or
diagnosis.

## Nexus RTK wrapper/proxy

Nexus includes a local wrapper:

```bash
scripts/nexus-rtk git status
scripts/nexus-rtk pytest
```

The wrapper:

1. runs `rtk <command>`;
2. prints RTK-filtered output back to the agent;
3. posts compact metadata to `/v1/rtk/events` if `NEXUS_SECRET` is set;
4. never sends raw command output by default.

Required environment:

```bash
export NEXUS_URL=http://localhost:7777
export NEXUS_SECRET=<secret>
export NEXUS_AGENT_ID=<agent-name>
```

To save a durable memory from a command event:

```bash
NEXUS_RTK_DURABLE=1 \
NEXUS_RTK_SUMMARY="pytest failed because migrations were missing; run alembic upgrade head first." \
scripts/nexus-rtk pytest
```

Agents with hook/proxy support can map noisy commands to `scripts/nexus-rtk ...`.
Agents without hook support should be instructed to call `rtk ...` directly and
save durable lessons through normal Nexus memory tools.

## Metrics endpoint

Dashboard and operations views can read aggregate RTK activity from:

```text
GET /v1/admin/rtk
```

It returns total command events, recent failures, top command labels, events by
agent, durable memories created from RTK summaries, and estimated token savings.

## Recommended `.env` balance

For “remember everything durable, but keep prompts cheap”:

```env
LLM_COST_SAVER=true
LLM_QUERY_EXPANSION=false
CONTEXT_MEMORY_LIMIT=20
CONTEXT_MEMORY_CHAR_LIMIT=500
CONTEXT_CONCLUSION_LIMIT=8
```

If you want richer startup context and accept higher token use:

```env
CONTEXT_MEMORY_LIMIT=40
CONTEXT_MEMORY_CHAR_LIMIT=900
CONTEXT_CONCLUSION_LIMIT=15
```

The database still stores full memory content either way; these settings only
control what is injected into active prompts.

## Bootstrap script

Use the repo helper:

```bash
bash scripts/setup-rtk.sh
```

It verifies the correct RTK binary, installs if needed, disables telemetry unless
you opt in, and optionally initializes Claude hooks.
