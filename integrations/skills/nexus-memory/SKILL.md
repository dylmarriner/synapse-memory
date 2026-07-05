---
name: nexus-memory
description: Save, recall, and reflect on durable long-term memories via Nexus. Use when the user says "remember this", "do you remember", or asks about prior work. Use proactively before non-trivial tasks to gather prior context, after completing work to record decisions, and after mistakes or corrections to save lessons.
argument-hint: "[recall <query>|save <content>|lesson <content>|reflect <query>]"
user-invocable: true
version: 1.0.0
author: Nexus
license: MIT
---

# Nexus Memory

Unified long-term memory shared across all agents and devices. 4-way parallel
recall (vector + lexical + graph + temporal) fused with Reciprocal Rank Fusion.

## When to recall — `memory_recall`

Recall **before** answering or starting work when prior context could help:

- "Do you remember…" / "What did we decide about…" / "What was that bug…"
- Beginning of a new task that touches prior work, decisions, or preferences
- Debugging something that may have been fixed before
- When the user references an earlier session or conversation

```
memory_recall(query="<question>", limit=8, memory_types=["preference","lesson","world"])
```

## When to save — `memory_save`

Save **after** events that matter:

- Decisions, architecture choices, or trade-offs
- Implementation patterns, conventions, or gotchas discovered
- User preferences: "I like…", "I prefer…", "I always…", "I never…"
- Project facts: "the API uses X", "we deploy on Y", "the owner is Z"
- The user says: "remember this", "note that", "keep in mind"

```
memory_save(
  content="<what to remember>",
  memory_type="world|experience|observation|preference",
  importance=0.5..0.9,
  tags=["project:foo","topic:bar"]
)
```

## When to save a lesson — `memory_save_lesson`

Lessons are **highest importance (0.9)**, never decayed, surface first in recall.

- After a mistake or wrong answer
- When the user corrects you ("no, that's wrong", "actually…")
- When you discover a non-obvious gotcha that prevents future errors

```
memory_save_lesson(content="I was wrong about X — correct answer is Y because Z")
```

## When to reflect — `memory_reflect`

LLM-synthesized answer from multiple memories. Use for questions that need
cross-cutting synthesis, not a single fact.

- "Summarize everything we know about this project"
- "What are the recurring issues with X?"
- "Walk me through the history of this decision"

```
memory_reflect(query="<topic>", depth="low|mid|high")
```

## When to share globally — `memory_save_global`

Promote a memory so every agent on the network sees it:

- Cross-project conventions
- User-wide preferences
- Foundational facts about the environment

## When to leave a handoff — `memory_handoff`

For peer agents: "When X starts a session, surface this".

```
memory_handoff(content="…", target_agent="other-agent-id")
```

## Tool reference

| Tool | Purpose |
|---|---|
| `memory_recall` | 4-way search across your memories |
| `memory_save` | Persist a new memory (typed: world/experience/observation/preference) |
| `memory_save_lesson` | High-priority correction or gotcha |
| `memory_save_global` | Promote memory to all agents |
| `memory_reflect` | LLM-synthesized answer from memories |
| `agent_context` | Load agent-specific context (representation, recent, conclusions) |
| `memory_handoff` | Leave a note for a specific agent |
| `nexus_status` | Check server health |

## Operational notes

- **Recall first, answer second** — a 5-second recall beats a wrong guess
- **Save once, recall forever** — don't make the user repeat themselves
- **Lessons are sacred** — if you learned something the hard way, save it
- **Don't pollute** — don't save trivial turns, greetings, or things already in code
- **Use metadata** — `tags` and `memory_type` make future recall dramatically better
