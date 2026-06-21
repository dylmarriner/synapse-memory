# nexus-handoff worked examples

## 1. Leaving a handoff note for another agent
User: "I'm stopping for the day. Make sure Cline knows what to do with the billing script tomorrow."

Invocation:
```json
memory_note_to_agent {
  "target_agent_id": "cline",
  "content": "Handoff: billing script refactor. The API schema is done in api/billing.ts, but tests are currently failing on line 42 (missing mock API token). Add JWT mock bypass to finish.",
  "importance": 0.8,
  "tags": ["handoff", "billing", "api-mock"]
}
```

Response:
```text
Note saved for agent 'cline': df43d81c...
```

Followup:
> I have left a dedicated handoff note for Cline in Nexus (id: df43d81c). The note contains instructions about completing the billing API schema mock in `api/billing.ts` to fix the test failures.

---

## 2. Rebuilding the agent's context representation before session end
User: "We've done a lot of work on this codebase. Refresh your profile so you recall this setup."

Invocation:
```json
agent_represent {
  "agent_id": "openclaw"
}
```

Response:
```text
Representation rebuilt for 'openclaw':
OpenClaw is a senior developer agent working on a Node.js/Python shared-memory backbone. It has implemented WAL-mode database optimizations, configured secure JWT session boundaries on FastAPI routing controllers, and established stable docker-compose development environments.
```

Followup:
> Done! I have updated my profile on Nexus. Whenever I or another session of OpenClaw starts up, our context pack will display this summarized representation first.
