export const SYNAPSE_AGENT_GUIDANCE = `
## Synapse Memory System

You have access to Synapse — a persistent AI memory backbone shared across
all tools and devices on the Tailscale mesh.

### Store memories when:
- Architecture decisions, conventions, gotchas, useful commands
- Bug fixes or workarounds you discover
- User preferences or project-specific patterns
- Session progress (what's done, what remains)

### Retrieve before:
- Starting work on a new task (\`synapse_context\`)
- Debugging (check for similar issues)
- Making changes (verify constraints)

### Memory kinds:
- \`semantic\` — durable knowledge that persists indefinitely
- \`episodic\` — timeline events, incidents, session notes  
- \`working\` — ephemeral context for current session

### Tools:
- \`synapse_store\` — Create memory (set importance 0.0-1.0)
- \`synapse_retrieve\` — Hybrid search by keyword
- \`synapse_context\` — Optimized context pack for prompts
- \`synapse_update\` — Merge/append to existing memories
- \`synapse_rank\` — Which memories are most valuable
- \`synapse_memory\` — Server health and stats
`;
