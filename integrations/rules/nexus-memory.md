## Nexus Memory

You have access to a Nexus Memory MCP server (or REST at `$NEXUS_URL/v1`).
Nexus is durable, shared long-term memory across all agents, devices, and
sessions on this network.

### Recall before answering

Run `memory_recall` **before** answering when prior context could help:
questions about prior work, decisions, preferences, debugging history, or
"do you remember…". One 5-second recall beats a wrong guess.

```
memory_recall(query="<the user's question>", limit=8)
```

### Save after doing work

Run `memory_save` **after** completing non-trivial work or when the user
shares preferences, decisions, or context worth remembering across sessions.

```
memory_save(
  content="<what to remember>",
  memory_type="preference|world|experience|observation",
  importance=0.5..0.9,
  tags=["project:foo","topic:bar"]
)
```

### Save lessons for corrections

Run `memory_save_lesson` after mistakes or corrections — these never decay
and surface first in future recall.

```
memory_save_lesson(content="I was wrong about X — correct answer is Y because Z")
```

### Use reflect for synthesis

Run `memory_reflect` when a question needs cross-cutting synthesis from
multiple memories, not a single fact.

### Other tools

- `memory_save_global` — promote a memory so every agent on the network sees it
- `agent_context` — load your agent-specific context (representation, conclusions, recent)
- `memory_handoff` — leave a note for a specific peer agent
- `memory_consolidate` / `memory_confirm` / `memory_contradict` — keep memory clean
- `nexus_status` — check server health

### Don't pollute

Don't save greetings, trivial turns, or facts already in code. When in doubt,
recall first and only save what's worth a future recall.

### REST fallback

If MCP is unavailable, call `$NEXUS_URL/v1/memory/{save,recall,reflect}` etc.
with `Authorization: Bearer $NEXUS_SECRET`. See `UNIVERSAL_AGENT_INTEGRATION.md`.
