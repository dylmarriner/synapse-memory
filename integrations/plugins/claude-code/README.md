# Nexus Memory — Claude Code Plugin

Connects Claude Code to the Nexus unified long-term memory server.

## Install

```bash
claude plugin install /path/to/synapse-memory/integrations/plugins/claude-code
```

Or from the marketplace once published:

```bash
claude plugin install nexus-memory
```

## Configuration

Set these environment variables (in your shell or `~/.claude/settings.json`):

```bash
export NEXUS_URL="http://100.93.75.87:7777"
export NEXUS_SECRET="<your-bearer-secret>"
```

## What you get

- `memory_recall` — search Nexus memory with 4-way recall
- `memory_save` — save durable context, decisions, preferences
- `memory_save_lesson` — save corrections as high-importance lessons
- `memory_reflect` — synthesize memories into structured reflection
- `agent_context` — load agent-specific context
- `nexus_status` — check server health

See `https://github.com/dylmarriner/synapse-memory` for the full tool list and REST examples.
