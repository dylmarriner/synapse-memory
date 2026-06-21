# nexus-remember worked examples

## 1. Saving a user preference
User: "Keep in mind that I prefer using lowercase for all SQL table names."

Invocation:
```json
memory_save {
  "content": "User prefers lowercase for all SQL table names on Postgres schemas.",
  "importance": 0.85,
  "tags": ["sql", "convention", "postgres"]
}
```

Response:
```text
Memory saved: ea748fa1...
```

Followup:
> I have saved your SQL naming convention preference to the Nexus memory backbone (id: ea748fa1) with tags: `sql`, `convention`, `postgres`. This preference will be automatically active in our future sessions.

---

## 2. Saving a critical correction (Lesson Learn)
User: "No, don't use 'npm install' here, we are using pnpm workspace and lockfiles!"

Invocation:
```json
memory_save_lesson {
  "content": "I mistakenly attempted to use 'npm install' in this repository. We are using pnpm workspace which relies on a pnpm-lock.yaml. Using npm breaks package boundaries; always run pnpm commands.",
  "tags": ["package-manager", "pnpm", "correction"]
}
```

Response:
```text
Lesson saved: 3fd28ab0...
```

---

## 3. Saving a global fact (Visible to all agents)
User: "Make sure all our agents know we've upgraded the dev-db port to 5435."

Invocation:
```json
memory_save_global {
  "content": "The development Postgres database port has changed from 5432 to 5435.",
  "memory_type": "world",
  "importance": 0.8,
  "tags": ["database", "ports", "postgres"]
}
```

Response:
```text
Global memory saved: b34ff71a...
```
