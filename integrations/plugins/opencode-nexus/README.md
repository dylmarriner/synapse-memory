# @nexus/memory — OpenCode Plugin

Nexus unified long-term memory for OpenCode. 4-way recall (vector + lexical + graph + temporal), durable save, lessons, structured reflection.

## Install

```bash
opencode plugin install @nexus/memory --global
```

Or as a project plugin:

```bash
opencode plugin install @nexus/memory
```

## Configuration

Set these environment variables (or use opencode.json):

```json
{
  "env": {
    "NEXUS_URL": "http://100.93.75.87:7777",
    "NEXUS_SECRET": "<your-bearer-secret>",
    "NEXUS_AGENT_ID": "opencode"
  }
}
```

## What it does

- **Auto-recall**: injects top 5 relevant memories into every chat turn as `[Nexus memory context:]`.
- **Auto-save**: after each turn, captures informational content (preferences, decisions, "remember that...") as `experience` memories.
- **Tools**: registers `nexus_recall`, `nexus_save`, `nexus_reflect`, `nexus_status` for the LLM to call.

## License

MIT
