export const NEXUS_AGENT_GUIDANCE = `
## Nexus Memory System

You have access to Nexus — a unified persistent AI memory backbone shared across
all tools and devices on the Tailscale mesh (semantic · lexical · graph · temporal recall).

### Save memories when:
- Architecture decisions, conventions, gotchas, useful commands
- Bug fixes or workarounds you discover
- User preferences or project-specific patterns
- Session progress (what's done, what remains)
- Lessons learned from mistakes

### Recall before:
- Starting work on a new task (\`nexus_recall\` or \`nexus_context\`)
- Debugging (check for similar issues)
- Making changes (verify constraints and past decisions)

### Memory types:
- \`world\` — durable facts about the codebase or domain
- \`experience\` — session events, incidents, outcomes
- \`observation\` — things noticed during work
- \`preference\` — user or project preferences
- \`lesson\` — corrections and mistakes to avoid (highest priority)

### Tools:
- \`nexus_save\` — Save a memory (importance 0.0-1.0)
- \`nexus_recall\` — 4-way hybrid search
- \`nexus_context\` — Full agent context pack
- \`nexus_reflect\` — LLM synthesis over memories
- \`nexus_status\` — Server health
`;
