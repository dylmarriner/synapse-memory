# OpenClaw + Living Mind

Legacy integration for the optional Living Mind layer. Default Nexus
deployments now use direct agent-to-memory interaction.

## Install

The OpenClaw plugin manager handles installation.  From the
synapse-memory repo root:

```bash
openclaw plugin install /path/to/synapse-memory/integrations/plugins/openclaw-mind
```

Or copy the plugin into the OpenClaw extensions directory:

```bash
cp -r integrations/plugins/openclaw-mind ~/.openclaw/extensions/mind
```

## Configure

The plugin reads four env vars at startup:

```bash
export NEXUS_URL="http://localhost:7777"
export NEXUS_SECRET="your-bearer-token"
export MIND_ID="default"
export AGENT_ID="openclaw"
```

## What the agent gets

- **At session start**: a briefing from the mind — its identity,
  proactive context (unfinished promises, recent related work,
  contradictions), and its opinions.  Injected into the system
  prompt.
- **At every prompt**: just-in-time context relevant to that
  specific prompt.
- **After every tool use**: the mind captures a concise
  observation for later recall and learning.
- **At session end**: the mind saves a session summary so the
  next session has continuity.
- **Available MCP tools**: `mind_think`, `mind_reflect`, `mind_get_*`
  (when the MCP server is also configured).

## See Also

- [Claude Code + Living Mind](../claude-code-mind/README.md)
- [OpenCode + Living Mind](../opencode-mind/README.md)
- [Hermes + Living Mind](../hermes-mind/README.md)
- [Living Mind Architecture](../../../docs/living-mind/ARCHITECTURE.md)
