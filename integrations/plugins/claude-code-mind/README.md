# Claude Code + Living Mind

Legacy integration for the optional Living Mind layer. Default Nexus
deployments now use direct agent-to-memory interaction.

## What the agent gets

- **At session start**: a briefing from the mind — its identity,
  proactive context (unfinished promises, recent related work,
  contradictions), and its opinions.
- **At every prompt**: the mind surfaces context relevant to
  that specific prompt.
- **After every tool use**: the mind captures a concise
  observation for later recall and learning.
- **At session end**: the mind saves a session summary so the
  next session has continuity.

## Install

```bash
# Copy the plugin
cp -r integrations/plugins/claude-code-mind ~/.claude/plugins/mind

# Or use the plugin install command
claude plugin install /path/to/synapse-memory/integrations/plugins/claude-code-mind
```

## Configure

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "NEXUS_URL":    "http://localhost:7777",
    "NEXUS_SECRET": "your-bearer-token",
    "MIND_ID":      "default",
    "AGENT_ID":     "claude-code"
  },
  "hooks": {
    "SessionStart":     ["python3 $PLUGIN_DIR/hooks/session_start.py"],
    "UserPromptSubmit": ["python3 $PLUGIN_DIR/hooks/prompt_submit.py"],
    "PostToolUse":      ["python3 $PLUGIN_DIR/hooks/post_tool_use.py"],
    "Stop":             ["python3 $PLUGIN_DIR/hooks/session_end.py"]
  }
}
```

## Available MCP tools

When connected, the agent gets these `mind_*` tools:

- `mind_think` — ask the mind a question, get a reasoned response
- `mind_reflect` — deep reflection on a topic
- `mind_start_conversation` / `mind_conversation_turn` / `mind_end_conversation` — multi-turn dialogue
- `mind_get_identity` — the mind's self-model
- `mind_get_opinions` — the mind's opinions
- `mind_get_proactive` — proactive context without asking

## What the agent sees

When the plugin is installed and the Nexus server is running, the
agent's system prompt includes something like:

```
## Living Mind Identity

You are working with a living mind that has:
  - I am a living mind, a reasoning agent over my memories.
  - I form opinions based on accumulated evidence.
  - I proactively surface context without being asked.
- 12 learned patterns from experience
- 3 known capabilities
- 1 relationship

## Proactive Context (from the Living Mind)

- [unfinished_promise] You committed to: refactor the auth module (relevance 0.95)
- [recent_work] Recently: fixed JWT refresh bug (relevance 0.85)
- [pattern] Multiple bug memories (3) about this topic (relevance 0.70)

## Mind's Opinions

- **auth_module**: negative (strength 0.80, 5 pieces of evidence)
```

## How it works

1. **session_start.py** calls `GET /v1/mind/identity/{mind_id}`,
   `POST /v1/mind/think` (for proactive), and `GET /v1/mind/opinions/{mind_id}`.
2. **prompt_submit.py** calls `POST /v1/mind/think` with the
   user's prompt at `reasoning_depth=fast` to get just-in-time
   proactive context.
3. **post_tool_use.py** calls `POST /v1/memory/save` with a
   concise observation.  The Nexus memory router on the server
   side processes it through the mind.
4. **session_end.py** calls `POST /v1/memory/save` with a
   session summary so the next session has continuity.

All hooks are fire-and-forget: 3-8 second timeouts, no failure
propagation, the agent never blocks on memory.

## Troubleshooting

- **No briefing at session start**: check `NEXUS_SECRET` is set
  and the server is reachable.  Try `curl $NEXUS_URL/health`.
- **"Mind's Opinions" is empty**: the mind has no opinions yet.
  It forms opinions as it processes interactions with at least
  3 pieces of evidence.  Keep using the agent — they'll accumulate.
- **Hooks never fire**: verify the path to `$PLUGIN_DIR` in your
  Claude Code settings.  Claude Code expands it to the plugin
  install directory.
