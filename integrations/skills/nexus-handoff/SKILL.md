---
name: nexus-handoff
description: Save a summary of work completed, active preferences, outstanding tasks, or dev-tunnel status so the next agent session or a peer agent picks up smoothly. Use at the END of a session, when transferring a task, or when completing work to maintain continuity.
argument-hint: "[handoff statement or summary notes]"
user-invocable: true
---

The user wants to record a handoff or context pack in Nexus: $ARGUMENTS

## Quick start

### Creating a note directly for a peer agent
```json
memory_note_to_agent {
  "target_agent_id": "cline",
  "content": "Work-in-progress: added SQL tables but migrations are deferred. Run scripts/db-migrate.sh to start up.",
  "importance": 0.75,
  "tags": ["handoff", "migrations", "db-up"]
}
```

### Rebuilding agent profile context (at the end of session)
```json
agent_represent {
  "agent_id": "openclaw"
}
```

## Why
Nexus maintains a dynamic context-compilation block on each agent. By explicitly leaving notes or rebuilding representations, you prevent the "context drift" that happens across disjointed SSH, terminal, or gateway session boundaries.

## Workflow
1. Synthesize the session's work:
   - What was done.
   - What was left unfinished.
   - Specific instructions or test commands to run next.
2. Determine the delivery route:
   - **Specific Agent Profile**: To notify or guide a specific agent (e.g., Cline, OpenClaw, Hermes), use `memory_note_to_agent`.
   - **General Handoff Fact**: Save via `memory_save` (importance 0.7, tagged "handoff").
3. Trigger `agent_represent` for your own `agent_id` so the global profile reflects this new work in the next session warmup.
4. Echo details of the handoff or represent-build to the user.

## See also
- `nexus-remember`: For generic writes.
- `nexus-recall`: Retrieving general history.
