---
name: nexus-remember
description: Save an important lesson, user preference, architectural decision, or codebase fact permanently to the Nexus unified memory network. Use when learning something new, receiving corrections, noting user choices, discovering workarounds, or completing a task session.
argument-hint: "[insights, fact, preference, or lesson to remember]"
user-invocable: true
---

The user wants to save this context to Nexus long-term memory: $ARGUMENTS

## Quick start

### Save general memory (fact, convention, preference)
```json
memory_save {
  "content": "In project X, we use Vitest instead of Jest for all unit tests to align with ES modules.",
  "importance": 0.8,
  "tags": ["testing", "vitest", "esm"]
}
```

### Save a lesson (critical corrections, bug workarounds, mistakes)
```json
memory_save_lesson {
  "content": "I mistakenly tried to use mockDb in routing tests — we must use the actual fast-sqlite mock from test/fixtures/mock-db.ts to avoid transaction lockups.",
  "tags": ["database", "testing-error"]
}
```

### Save global memory (visible to ALL agents on all devices)
```json
memory_save_global {
  "content": "Nexus server runs at http://100.93.75.87:7777 on the Tailscale mesh.",
  "memory_type": "world",
  "importance": 0.9,
  "tags": ["nexus", "infrastructure"]
}
```

## Why
Nexus is a unified cross-agent memory backbone. Storing clear, well-tagged facts makes you and other agents (Hermes, Cline, OpenCode, OpenClaw) smarter over time.

## Workflow
1. Extract the core insight, decision, or preference from the arguments.
2. Determine the scope:
   - **Lesson**: If you made a mistake or received a correction, ALWAYS use `memory_save_lesson`. Lesson memories have priority = 0.9 and never decay.
   - **Global**: If the knowledge is highly valuable for all agents globally, use `memory_save_global`.
   - **Durable Facts / Preferences**: Use `memory_save` (importance 0.5-0.8).
3. Call the appropriate tool with clean, concise content.
4. Confirm successful save with the generated resource ID.

## See also
- `nexus-recall`: The retrieval query skill.
- `nexus-handoff`: The handoff and note skill.
