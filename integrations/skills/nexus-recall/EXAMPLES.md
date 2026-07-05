# nexus-recall worked examples

## 1. Finding past decisions and lessons
User: "What was that database lockup bug we faced last week?"

Invocation:
```json
memory_recall {
  "query": "database lockup transaction sqlite",
  "limit": 5,
  "memory_types": ["lesson", "experience"]
}
```

Response:
```text
Found 2 memories:
1. [lesson] score=0.942 "Tried using multi-threading on Sqlite without WAL mode — locked the db. Fixed by enabling journal_mode=WAL on startup."
2. [experience] score=0.760 "Ran migration test concurrently which triggered isolation lockups."
```

Followup:
> Based on our Nexus memory, we encountered SQLite thread lockups last week (score: 0.942). The lesson saved was to avoid concurrent multi-threaded writes without WAL enabled. We fixed it by using `journal_mode=WAL` on startup.

---

## 2. Onboarding context search
User: "Summarize our Vitest config rules."

Invocation:
```json
memory_recall {
  "query": "Vitest config rules testing",
  "limit": 5
}
```

Response:
```text
Found 1 memory:
1. [world] score=0.880 "Vitest configuration mandates inline globals, threads: false, and environment: node."
```

Followup:
> Nexus holds our testing rules (score: 0.880): We use Vitest with inline globals enabled (`globals: true`), process isolation disabled (`threads: false`), and target the node environment.
