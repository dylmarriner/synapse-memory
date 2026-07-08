# Obelisk + Nexus Integration

Nexus is the durable memory layer. Obelisk is the command-output token optimizer.

Together they support the goal of remembering far more than single-agent memory
systems while keeping the active LLM context affordable:

- **Nexus remembers everything durable**: preferences, lessons, decisions,
  project facts, summaries, entities, contradictions, global shared knowledge,
  and cross-agent handoffs.
- **Obelisk reduces transient shell-output tokens** before they enter the model
  context: `git`, `ls`, `grep`/`rg`, `pytest`, `npm`/`pnpm`, `docker`,
  `kubectl`, `cargo`, and similar high-volume commands.

Obelisk does **not** replace Nexus, BrainSync, AgentMemory, Hindsight, or Honcho
as a memory store. It is a CLI optimizer and context compressor. The right
architecture is:

```text
Agent shell command → Obelisk optimizer → compact output to LLM
Agent facts/lessons/preferences → Nexus MCP/REST → PostgreSQL + pgvector + graph + temporal recall
```

## Why this is better than plain memory-only systems

Memory systems often fail because they either:

1. stuff too much history into every prompt, or
2. save too little to stay affordable.

Nexus + Obelisk separates those concerns:

- Store high-volume durable memory in Nexus.
- Retrieve only relevant context via fused vector/lexical/graph/temporal recall.
- Use Obelisk to prevent large command outputs from consuming the live context.
- Preserve full source-of-truth data in the database, while summaries and
  context packs are token-bounded views.

## Install Obelisk

First verify whether the correct Obelisk binary is already installed:

```bash
obelisk --version
obelisk doctor
which obelisk
```

`obelisk doctor` should succeed. If it does not, install Obelisk following the
project documentation and ensure the binary is on `PATH`.

## Agent command policy

Agents should prefer Obelisk for commands that generate noisy output:

```bash
obelisk run git status
obelisk run cargo build
obelisk run pytest
obelisk run npm test
obelisk run pnpm test
obelisk run docker ps
obelisk run kubectl get pods
obelisk run rg "pattern" app
```

Use raw commands only when exact unfiltered output is required.

## Nexus memory policy with Obelisk

Obelisk should never be used as an excuse to save less. It only reduces live
command tokens. Nexus should still save durable facts aggressively:

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
