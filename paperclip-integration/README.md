# Paperclip Nexus Adapter Integration

This adapter enables Paperclip-managed agents to use Nexus as their memory backend instead of Paperclip's internal database.

## Overview

Paperclip's `plugin-agent-memory` plugin provides comprehensive memory infrastructure (store, recall, decay, indexing, shared state). This adapter replaces the internal DB calls with Nexus API calls while maintaining the same interface.

## Features

- **Unified Memory Backend**: All Paperclip agents can share the same Nexus memory server
- **Cross-Platform Memory Sharing**: Hermes agents, OpenClaw agents, and Paperclip agents can share memories via `agent_id: "global"`
- **Automatic Type Mapping**: Paperclip MemoryKind system maps directly to Nexus memory types
- **Agent Identity Sync**: Paperclip agent identities are automatically synced to Nexus
- **Agent Registry**: Paperclip agents are discoverable via the Nexus agent registry
- **Fallback Support**: Graceful fallback to internal DB if Nexus is unavailable

## Memory Type Mapping

| Paperclip MemoryKind | Nexus Memory Type | Description |
|---------------------|------------------|-------------|
| `identity` | `world` | Agent identity and system prompts |
| `project_context` | `world` | Project-specific context and files |
| `file_knowledge` | `world` | File and code knowledge |
| `decision` | `observation` | Decisions made during development |
| `task_context` | `experience` | Task-related experiences |
| `error_pattern` | `lesson` | Error patterns and solutions |
| `session_summary` | `experience` | Session summaries |
| `user_preference` | `preference` | User preferences and settings |
| `agent_observation` | `observation` | General agent observations |

## Installation

### 1. Add the adapter to your Paperclip plugin

Copy `nexus-adapter.ts` to your Paperclip plugin directory:
```
packages/plugins/plugin-agent-memory/src/nexus-adapter.ts
```

### 2. Update the plugin configuration

In `packages/plugins/plugin-agent-memory/src/config/schema.ts`, add the Nexus configuration:

```typescript
import { nexusConfigSchema, instanceConfigSchema } from './nexus-adapter';

export const instanceConfigSchema = nexusConfigSchema.extend({
  // Your existing config fields...
});
```

### 3. Update the plugin manifest

In `packages/plugins/plugin-agent-memory/src/manifest.ts`:

```typescript
instanceConfigSchema: instanceConfigSchema.extend({
  nexusUrl: z.string().optional(),
  nexusSecret: z.string().optional(),
  nexusEnabled: z.boolean().optional(),
  agentId: z.string().optional(),
}),
```

### 4. Replace memory functions in the plugin

In `packages/plugins/plugin-agent-memory/src/memory/store.ts`:

```typescript
import { storeMemory as nexusStoreMemory } from '../nexus-adapter';

export async function storeMemory(ctx, input) {
  // Check if Nexus is enabled
  const config = ctx.instanceConfig;
  if (config.nexusEnabled) {
    return await nexusStoreMemory(ctx, input);
  }
  
  // Fall back to original implementation
  // ... existing code ...
}
```

Repeat similar changes for `recall.ts`, `decay.ts`, and any other memory functions.

### 5. Configure environment variables

Set the following environment variables:

```bash
NEXUS_URL=http://100.93.75.87:7777
NEXUS_SECRET=your-secret-here
NEXUS_ENABLED=true
AGENT_ID=your-paperclip-agent-id
```

### 6. Update agent instance configuration

In your Paperclip agent configuration:

```yaml
memory:
  enabled: true
  nexus_enabled: true
  nexus_url: http://100.93.75.87:7777
  agent_id: paperclip:my-agent
  sync_identity: true
  track_activity: true
  fallback_to_internal: true
```

## Usage Examples

### Storing memory

```typescript
await storeMemory(ctx, {
  content: "User prefers dark mode in all applications",
  kind: "user_preference",
  agentId: "paperclip:my-agent",
  importance: 8,
  companyId: "my-company"
});
```

This will be stored in Nexus as:
- `memory_type`: "preference"
- `agent_id`: "paperclip:my-agent"
- `importance`: 0.8 (normalized from 8)
- `tags`: ["user_preference"]
- `metadata`: { paperclip: true, company_id: "my-company" }

### Recalling memory

```typescript
const memories = await recall(ctx, {
  query: "user preferences for UI",
  agentId: "paperclip:my-agent",
  limit: 10
});
```

### Syncing agent identity

```typescript
await syncAgentIdentity(ctx, {
  agentId: "paperclip:my-agent",
  identity: "I am a specialized coding assistant that focuses on Python development..."
});
```

This stores the identity in both:
1. The agent's own memory (`agent_id: "paperclip:my-agent"`)
2. Global memory pool (`agent_id: "global"`) for cross-agent visibility

## Cross-Platform Memory Sharing

With Nexus as the backend, Paperclip agents can share memories with other platforms:

### Hermes agent remembers what Paperclip learned

```typescript
// Paperclip saves a decision
await storeMemory(ctx, {
  content: "We decided to use PostgreSQL instead of MongoDB for this project",
  kind: "decision",
  agentId: "paperclip:my-agent"
});

// Hermes agent can recall it
await recall(ctx, {
  query: "database decision",
  agentId: "hermes"  // Will find global memories too
});
```

### Global knowledge pool

Any memory saved with `agent_id: "global"` is visible to all agents across all platforms:

```typescript
await storeMemory(ctx, {
  content: "Company deployment policy: deploy to production on Tuesdays only",
  kind: "decision",
  agentId: "global"  // Visible to Hermes, OpenClaw, and Paperclip agents
});
```

## Agent Discovery

Paperclip agents can discover other agents via the Nexus agent registry:

```typescript
// Update agent activity for registry
await updateAgentActivity(ctx, {
  agentId: "paperclip:my-agent",
  model: "gpt-4",
  capabilities: ["coding", "code-review", "debugging"]
});

// Discover other agents
const response = await fetch(`${NEXUS_URL}/v1/agents/discover?model=gpt-4`);
const agents = await response.json();
```

## Health Monitoring

Check Nexus availability:

```typescript
const health = await healthCheck();
if (!health.healthy) {
  console.error("Nexus is unavailable, falling back to internal DB");
}
```

## Benefits

1. **Unified Memory**: All your agents share the same memory infrastructure
2. **Cost Efficiency**: Deduplicated storage and intelligent consolidation
3. **Advanced Recall**: 4-way recall (vector + lexical + graph + temporal)
4. **Agent Coordination**: Built-in support for multi-agent workflows
5. **Production Ready**: Battle-tested memory system with backup/export
6. **Token Optimization**: Smart context injection saves tokens
7. **Scalability**: HNSW vector indexes for performance at scale

## Troubleshooting

### Nexus connection fails

1. Check `NEXUS_URL` and `NEXUS_SECRET` environment variables
2. Verify Nexus server is running: `curl http://100.93.75.87:7777/health`
3. Check network connectivity from Paperclip to Nexus

### Memory not appearing in recall

1. Verify the agent_id matches between store and recall
2. Check if memory types are correctly mapped
3. Use the Nexus dashboard to inspect stored memories

### Performance issues

1. Ensure HNSW indexes are created on the memories table
2. Check if Redis caching is enabled for embeddings
3. Monitor consolidation runs for memory bloat

## Migration Path

For existing Paperclip deployments with internal DB memories:

1. **Phase 1**: Enable Nexus with `fallback_to_internal: true`
2. **Phase 2**: Use Paperclip's export functionality to dump existing memories
3. **Phase 3**: Import memories into Nexus via `/v1/admin/import`
4. **Phase 4**: Set `fallback_to_internal: false` to use Nexus exclusively

## Support

For issues or questions:
- Nexus documentation: Check the Nexus dashboard at `http://100.93.75.87:7777/`
- Paperclip documentation: Refer to your Paperclip installation docs
- API endpoints: All Nexus API endpoints are documented via OpenAPI at `/docs`