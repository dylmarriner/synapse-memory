# Hermes + Living Mind

Legacy integration for the optional Living Mind layer. Default Nexus
deployments now use direct agent-to-memory interaction.

## Install

```bash
# Copy the plugin into Hermes's plugins directory
cp -r integrations/plugins/hermes-mind ~/.hermes/hermes-agent/plugins/memory/mind
```

## Configure

In `~/.hermes/config.yaml`:

```yaml
plugins:
  mind:
    nexus_url: "http://localhost:7777"
    nexus_secret: "your-bearer-token"
    mind_id: "default"
    agent_id: "hermes"
```

Or via environment variables:

```bash
export NEXUS_URL="http://localhost:7777"
export NEXUS_SECRET="your-bearer-token"
export MIND_ID="default"
export AGENT_ID="hermes"
```

## What the agent gets

Three Python hook functions:

- `on_session_start(context)` — Returns a `system_prompt_addition`
  the agent prepends to its system prompt.
- `on_prompt_submit(prompt, context)` — Returns a `context_addition`
  the agent prepends to the next turn.
- `on_session_end(summary, context)` — Saves a session summary as
  a memory for continuity.

## See Also

- [Claude Code + Living Mind](../claude-code-mind/README.md)
- [OpenCode + Living Mind](../opencode-mind/README.md)
- [Living Mind Architecture](../../../docs/living-mind/ARCHITECTURE.md)
