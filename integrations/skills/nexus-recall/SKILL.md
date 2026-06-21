---
name: nexus-recall
description: Search the Nexus unified memory network for past observation history, human/agent-to-agent decisions, lessons, and configurations. Use when starting a new task, when asked "what did we do", "where did we leave off", "did we hit this error", or when you need user preferences.
argument-hint: "[search query]"
user-invocable: true
---

The user wants to query past memories in Nexus for context on: $ARGUMENTS

## Quick start

### Comprehensive Multi-Mode Recall
```json
memory_recall {
  "query": "JWT session signing key change",
  "limit": 6
}
```

### Scoped Recall (filtering by memory type)
```json
memory_recall {
  "query": "Vitest setup",
  "limit": 5,
  "memory_types": ["world", "lesson"]
}
```

## Why
Nexus fuses four recall modes (vector distance, BM25 keyword matching, entity relation graph, and temporal sequence) into a single Reciprocal Rank Fusion index. It retrieves memories across all devices and agents, giving you full developer context.

## Workflow
1. Identify the core search terms from `$ARGUMENTS`.
2. Determine if any scope limits apply:
   - High priority: lessons (avoid mistakes) and rules.
   - Limit: Default results count is 10. Adjust lower (e.g. 5-7) to preserve token context if needed.
3. Call `memory_recall`.
4. Group and present the results clearly to the user:
   - Highlight any high-priority lessons or rules first.
   - Reference the score/type if relevant.
5. If no memories are matched, suggest alternative keywords or ask `agent_context`.

## See also
- `nexus-remember`: The writing/storing skill.
- `nexus-handoff`: Leaving handoff notes and summaries.
