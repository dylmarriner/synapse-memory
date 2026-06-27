# Migrating to the Living Mind

The Living Mind is an additive layer on top of the existing Nexus
memory server.  You can adopt it gradually without disrupting any
current agent.

This guide covers the three common adoption paths:

  1. **Side-by-side** — Mind runs in parallel with the existing
     memory tools; agents can opt in.
  2. **Active memory** — Mind transparently wraps every
     `memory_save` and `memory_recall`; agents get reasoned
     responses automatically.
  3. **Replace** — Disable the old direct memory tools; agents
     use only the mind tools.

## Path 1: Side-by-side (recommended for evaluation)

The mind lives next to your existing memory tools.  Agents call
`memory_save`/`memory_recall` as before, *and* the new
`mind_think`/`mind_get_*` tools are available alongside them.

### Steps

1. **Deploy the latest Nexus** (which includes the mind + migration 006).
   ```bash
   docker compose down
   git pull
   docker compose up -d
   # Migration 006 runs automatically on first start.
   ```

2. **Install the plugin** for your agent:
   ```bash
   scripts/install-living-mind claude-code
   ```

3. **Configure the env** (the installer prints this):
   ```bash
   export NEXUS_URL="http://localhost:7777"
   export NEXUS_SECRET="your-bearer-token"
   export MIND_ID="default"
   export AGENT_ID="claude-code"
   ```

4. **Restart the agent**.  At session start, the mind briefing
   appears in the system prompt.  The agent now has both old
   memory tools and new mind tools.

5. **Encourage the agent to use the mind** for new questions.
   The mind-memory skill teaches it when to prefer the mind over
   direct memory:
   ```
   mind_think("What do you know about X?")
   mind_get_opinions(topic="auth_module")
   ```

### What you keep

- All existing memories
- All existing memory tools
- All existing agent workflows
- All existing integrations

### What you add

- The mind briefing at session start
- The 8 `mind_*` MCP tools
- Mind-managed conversations and opinions
- Proactive context surfacing

## Path 2: Active Memory (transparent routing)

The mind wraps every `memory_save` and `memory_recall` call.  The
agent calls them as usual; the mind reasons about the memory in the
background.

### Steps

1-3: same as Path 1.

4. **Enable the active-memory layer** by flipping the
   `USE_ACTIVE_MEMORY` env flag (default: off):
   ```bash
   export USE_ACTIVE_MEMORY=1
   ```

5. **Wire the router**: the memory router replaces the direct
   memory operations with mind-routed ones.  Add to your agent
   plugin or wrapper:
   ```python
   from app.mind.active import MemoryRouter
   from app.routers.mind import _get_mind

   mind = _get_mind("default")
   router = MemoryRouter(mind)

   # Replace memory_save
   async def save(content, **kwargs):
       return await router.save(content, **kwargs)

   # Replace memory_recall
   async def recall(query, **kwargs):
       return await router.recall(query, **kwargs)
   ```

### What you keep

- All existing memory operations work as before
- Existing tool names and signatures

### What changes

- Saves now go through the mind (which extracts entities, forms
  opinions, updates identity)
- Recalls return reasoned answers instead of raw memory lists
- Every save/recall is an opportunity for the mind to learn

## Path 3: Replace (mind only)

Disable the old direct memory tools.  The agent uses only the
mind tools.

### Steps

1-3: same as Path 1.

4. **Replace the memory tools** in the agent's MCP tool list.
   Instead of `memory_save`/`memory_recall`, expose only:
   - `mind_think` (for context)
   - `mind_save_observation` (for captures)
   - `mind_get_proactive` (for proactive context)

5. **Update agent skills/rules** to point to the new tool names.

### When to choose this path

- You're starting fresh (no existing tools to preserve)
- You want the simplest agent surface
- You're confident the mind is the right abstraction

## Data migration

The Living Mind does **not** migrate your existing memories.  They
stay in the `memories` table; the mind queries them on demand
through the existing 4-mode fused recall.

If you want the mind to have rich context for a specific topic
without going through full recall, you can pre-populate its
identity:

```bash
# Add a pattern the mind should know about
curl -X POST http://localhost:7777/v1/memory/save \
  -H "Authorization: Bearer $NEXUS_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Our team uses Postgres for the primary database",
    "agent_id": "default",
    "memory_type": "world",
    "importance": 0.9,
    "tags": ["team_context"]
  }'
```

Then the next time any agent runs `mind_think` about database work,
that fact will be in the recall pool.

## Rolling back

If you decide the mind isn't working for you:

1. Set `USE_ACTIVE_MEMORY=0` (or unset it).
2. Agents go back to direct memory tools.
3. The mind stays in the database but is unused.
4. No data is lost — all memories, conversations, and opinions
   remain in the database.

## Monitoring

To see the mind in action:

```bash
# List all minds
scripts/mind-cli list

# Show one mind's full state
scripts/mind-cli show default

# Ask a question
scripts/mind-cli think default "What do you know about auth?"

# Reflect deeply
scripts/mind-cli reflect default "our development process"

# Check opinions
scripts/mind-cli opinions default
```

For HTTP-level monitoring:

```bash
# Health
curl http://localhost:7777/health

# Mind registry
curl -H "Authorization: Bearer $NEXUS_SECRET" \
  http://localhost:7777/v1/mind/registry
```

## Compatibility matrix

| Agent | Mind plugin | Direct memory still works? |
|---|---|---|
| Claude Code | `claude-code-mind` | Yes (configurable) |
| OpenCode | `opencode-mind` | Yes |
| Hermes | `hermes-mind` | Yes |
| OpenClaw | `openclaw-mind` | Yes |
| Other (any MCP client) | Use the MCP tools directly | Yes |

## Common questions

**Q: Does the mind replace the existing memory tools?**
A: No. The mind is an *additional* layer.  Existing tools continue
   to work; the mind is available alongside them.

**Q: How much does the mind cost?**
A: Each `think()` call costs one LLM call (for the reasoning step).
   The deterministic pipeline runs without an LLM and is fast (~5ms).
   In fast mode, the LLM call is the only network/LLM cost.

**Q: Can the mind run without an LLM?**
A: Yes. The deterministic pipeline produces reasoned answers from
   memories without any LLM call.  The LLM is used to improve the
   quality of patterns, insights, and opinions — but the system
   works without it.

**Q: What about agent-specific data?**
A: The mind stores agent relationships (trust, interaction count,
   shared projects) per agent.  This data is in `mind_relationships`
   and is preserved across agent restarts.

**Q: How does the mind handle disagreements?**
A: When new evidence contradicts an existing opinion, the mind
   uses a weighted average that lets strong new evidence dominate
   rather than averaging.  See `OpinionSystem.form_or_update` for
   the exact logic.

## See Also

- [Living Mind Architecture](ARCHITECTURE.md)
- [Living Mind as Active Memory](ACTIVE_MEMORY.md)
- [Integration Guide](INTEGRATION.md)
- [Adopted Patterns README](../../app/adopted/README.md) (in code)
