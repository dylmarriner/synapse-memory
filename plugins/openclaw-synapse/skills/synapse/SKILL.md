---
description: Use Synapse Memory to persist and retrieve project knowledge across sessions, tools, and devices.
---

# Synapse Memory

Synapse is the enterprise-grade multi-tenant memory backbone for AI agents.
It provides durable, cross-device, event-sourced memory — think "persistent brain"
for your coding workflow.

## How it works

1. **Store** conventions, gotchas, architecture decisions, commands, and progress
2. **Retrieve** relevant memories before starting any task
3. **Update** memories when context evolves
4. **Context pack** auto-injects compressed memories into agent prompts

## Memory kinds

- **semantic**: Durable knowledge that should persist indefinitely
- **episodic**: Timeline events, incidents, session notes
- **working**: Ephemeral context for the current session

## Key tools

- `synapse_store` — Create a durable memory
- `synapse_retrieve` — Hybrid keyword + semantic search
- `synapse_context` — Optimized context pack for prompt injection
- `synapse_update` — Merge/overwrite/append to existing memories
- `synapse_rank` — Rank by importance, access frequency, and decay
- `synapse_memory` — Check server status and stats
