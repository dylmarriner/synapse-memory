# Nexus Memory Skill

Use Nexus as durable cross-agent memory.

## Before starting non-trivial work
1. Call `memory_recall` with the user's task, repository/project names, and active agent id.
2. Call `agent_context` for your agent id when you need current preferences, rules, or device handoff notes.

## During work
- Save durable facts, decisions, user preferences, project conventions, errors, and lessons with `memory_save`.
- Use `memory_save_lesson` after corrections or mistakes.
- Use `memory_save_global` for knowledge all agents should share.
- Use `memory_note_to_agent` for handoffs.

## Metadata to include on saves
Always include metadata when possible:

```json
{
  "device": "<device or hostname>",
  "hostname": "<hostname>",
  "source": "<cline|opencode|openhands|openhuman|paperclip|openclaw|custom>",
  "model": "<model name>",
  "workspace": "<absolute path or project>",
  "capabilities": ["coding", "terminal", "browser"]
}
```

## Agent IDs
Use stable IDs:
- `cline:<device>:<workspace-slug>`
- `opencode:<device>:<workspace-slug>`
- `openhands:<device>`
- `openhuman:<device>`
- `custom:<device>:<agent-name>`
