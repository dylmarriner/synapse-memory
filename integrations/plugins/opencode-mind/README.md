# OpenCode + Living Mind

Wires OpenCode to a running Nexus server's Living Mind.  The agent's
system prompt is seeded with the mind's briefing at session start,
and the mind surfaces relevant context before every prompt.

## Install

```bash
# Copy or symlink the plugin
cp -r integrations/plugins/opencode-mind ~/.opencode/plugins/mind

# Or install via OpenCode's plugin manager
opencode plugin install /path/to/synapse-memory/integrations/plugins/opencode-mind
```

## Configure

Add to `~/.opencode/settings.json`:

```json
{
  "env": {
    "NEXUS_URL":    "http://localhost:7777",
    "NEXUS_SECRET": "your-bearer-token",
    "MIND_ID":      "default",
    "AGENT_ID":     "opencode"
  },
  "hooks": {
    "session_start": "node $PLUGIN_DIR/hooks/session_start.mjs",
    "prompt_submit": "node $PLUGIN_DIR/hooks/prompt_submit.mjs"
  }
}
```

## What the agent gets

- **At session start**: a briefing from the mind (identity, proactive
  context, opinions).
- **At every prompt**: just-in-time context relevant to that prompt.
- **Available MCP tools**: `mind_think`, `mind_reflect`, `mind_get_*`
  (when the MCP server is also configured).

## See Also

- [Claude Code + Living Mind](../claude-code-mind/README.md)
- [Living Mind Architecture](../../../docs/living-mind/ARCHITECTURE.md)
