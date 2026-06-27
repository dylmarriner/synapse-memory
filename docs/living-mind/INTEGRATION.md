# Living Mind: Integration & Agent Connection

## Integration Architecture

### System Integration Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Layer                               │
│  Claude Code │ OpenCode │ Hermes │ OpenClaw │ Cline │ Cursor    │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│                    Connection Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │   MCP    │  │  Plugins │  │  Hooks   │  │   REST   │       │
│  │  Server  │  │          │  │          │  │   API    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│                    Living Mind Layer                             │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Living Mind Core                           │    │
│  │  • Reasoning Engine  • Identity  • Opinions            │    │
│  │  • Proactive Surfacing  • Learning  • Conversation      │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│                      Memory Layer                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Nexus Memory Server                        │    │
│  │  • 4-Mode Fused Search  • Entity Graph  • Consolidation│    │
│  │  • PostgreSQL + pgvector  • Redis  • Embeddings        │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Connection Flow

```
Agent starts session
        ↓
Hook fires: session_start
        ↓
Connection Layer receives event
        ↓
Living Mind builds briefing:
  - Agent identity
  - Recent work
  - Proactive context
  - Unfinished promises
        ↓
Briefing injected into agent context
        ↓
Agent works, asks questions
        ↓
MCP tool called: mind_think
        ↓
Living Mind reasons and responds
        ↓
Agent continues work
        ↓
Hook fires: post_tool_use
        ↓
Connection Layer captures observation
        ↓
Living Mind learns from interaction
        ↓
Session ends
        ↓
Hook fires: session_end
        ↓
Living Mind extracts learnings
        ↓
Identity updated
```

## MCP Tools for Living Mind

### Core Mind Tools

```python
# app/mcp.py - Add to existing MCP server

@mcp_tool()
async def mind_think(
    mind_id: str,
    question: str,
    context: Optional[Dict] = None,
    reasoning_depth: str = "standard"
) -> Dict:
    """
    Ask the living mind a question and get a reasoned response.
    
    The mind will:
    - Retrieve relevant memories
    - Reason about them
    - Form opinions if appropriate
    - Surface proactive context
    - Ask clarifying questions if needed
    """
    mind = await get_mind(mind_id)
    response = await mind.think(question, context, reasoning_depth)
    return response.to_dict()

@mcp_tool()
async def mind_start_conversation(
    mind_id: str,
    agent_id: str
) -> Dict:
    """Start a multi-turn conversation with the mind."""
    conv_manager = get_conversation_manager(mind_id)
    conv_id = await conv_manager.start_conversation(agent_id)
    return {"conversation_id": conv_id}

@mcp_tool()
async def mind_conversation_turn(
    mind_id: str,
    conversation_id: str,
    message: str
) -> Dict:
    """Send a message in an ongoing conversation with the mind."""
    conv_manager = get_conversation_manager(mind_id)
    response = await conv_manager.process_turn(conversation_id, message)
    return response.to_dict()

@mcp_tool()
async def mind_end_conversation(
    mind_id: str,
    conversation_id: str
) -> Dict:
    """End a conversation and extract learnings."""
    conv_manager = get_conversation_manager(mind_id)
    await conv_manager.end_conversation(conversation_id)
    return {"status": "ended"}

@mcp_tool()
async def mind_reflect(
    mind_id: str,
    topic: str,
    depth: str = "mid"
) -> Dict:
    """Ask the mind to reflect deeply on a topic."""
    mind = await get_mind(mind_id)
    reflection = await mind.reflect(topic, depth)
    return reflection.to_dict()

@mcp_tool()
async def mind_get_identity(mind_id: str) -> Dict:
    """Get the mind's current self-model."""
    mind = await get_mind(mind_id)
    return mind.identity.to_dict()

@mcp_tool()
async def mind_get_opinions(
    mind_id: str,
    topic: Optional[str] = None
) -> Dict:
    """Get the mind's opinions on topics."""
    mind = await get_mind(mind_id)
    if topic:
        opinion = mind.opinions.get(topic)
        return {"opinions": {topic: opinion.to_dict() if opinion else None}}
    return {"opinions": mind.opinions.to_dict()}

@mcp_tool()
async def mind_get_proactive_context(
    mind_id: str,
    agent_id: str,
    question: Optional[str] = None
) -> Dict:
    """Get proactive context the mind thinks is relevant."""
    mind = await get_mind(mind_id)
    proactive = mind.proactive.identify_context(question or "", [])
    return {"proactive_items": [item.to_dict() for item in proactive]}
```

## Agent Plugins

### Plugin Architecture

Each agent gets a plugin that:
- Registers MCP tools
- Installs hooks
- Provides skills
- Sets up rules

```
integrations/plugins/
├── claude-code-mind/          # Claude Code plugin
│   ├── plugin.json
│   ├── hooks/
│   │   ├── session_start.py
│   │   ├── prompt_submit.py
│   │   ├── post_tool_use.py
│   │   └── session_end.py
│   ├── skills/
│   │   └── mind-memory/
│   │       └── SKILL.md
│   └── README.md
│
├── opencode-mind/             # OpenCode plugin
│   ├── package.json
│   ├── hooks.json
│   ├── skills/
│   │   └── mind-memory/
│   │       └── SKILL.md
│   └── README.md
│
├── hermes-mind/               # Hermes plugin
│   ├── __init__.py
│   ├── plugin.yaml
│   ├── hooks/
│   │   ├── session_start.py
│   │   └── session_end.py
│   ├── skills/
│   │   └── mind-memory/
│   │       └── SKILL.md
│   └── README.md
│
└── openclaw-mind/             # OpenClaw plugin
    ├── package.json
    ├── hooks.json
    ├── skills/
    │   └── mind-memory/
    │       └── SKILL.md
    └── README.md
```

### Claude Code Plugin Example

```json
// integrations/plugins/claude-code-mind/plugin.json
{
  "name": "claude-code-mind",
  "version": "1.0.0",
  "description": "Living Mind integration for Claude Code",
  "mcpServers": {
    "mind": {
      "url": "${MIND_URL}",
      "headers": {
        "Authorization": "Bearer ${MIND_SECRET}"
      }
    }
  },
  "hooks": {
    "SessionStart": "hooks/session_start.py",
    "UserPromptSubmit": "hooks/prompt_submit.py",
    "PostToolUse": "hooks/post_tool_use.py",
    "Stop": "hooks/session_end.py"
  },
  "skills": [
    "skills/mind-memory"
  ]
}
```

## Hooks System

### Hook Taxonomy

```python
class HookEvent(str, Enum):
    """Living Mind hook events."""
    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    
    # User interaction
    PROMPT_SUBMIT = "prompt_submit"
    
    # Tool usage
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_FAILURE = "post_tool_failure"
    
    # Mind interaction
    MIND_QUESTION = "mind_question"
    MIND_RESPONSE = "mind_response"
    MIND_CONVERSATION_START = "mind_conversation_start"
    MIND_CONVERSATION_END = "mind_conversation_end"
    
    # Learning
    MIND_LEARNING_EXTRACTED = "mind_learning_extracted"
    MIND_IDENTITY_UPDATED = "mind_identity_updated"
    MIND_OPINION_FORMED = "mind_opinion_formed"
    
    # Proactive
    MIND_PROACTIVE_SURFACE = "mind_proactive_surface"
    
    # Context management
    PRE_COMPACT = "pre_compact"
    
    # Sub-agents
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    
    # Notifications
    NOTIFICATION = "notification"
    
    # Task completion
    TASK_COMPLETED = "task_completed"
```

## Skills

### Mind Memory Skill

The `mind-memory` skill teaches agents when and how to use the Living Mind.

**Key workflows:**
1. **Session Start Briefing** - Get proactive context at session start
2. **Contextual Question** - Ask the mind for context about a topic
3. **Multi-Turn Conversation** - Explore complex topics through dialogue
4. **Deep Reflection** - Get deep insights on a topic
5. **Opinion Seeking** - Get the mind's perspective on decisions

See `integrations/skills/mind-memory/SKILL.md` for full documentation.

## Rules (Global Instructions)

The `living-mind.md` rules file teaches agents:
- When to use the Living Mind vs direct memory
- Core principles of mind interaction
- Workflow integration patterns
- Best practices and troubleshooting

See `integrations/rules/living-mind.md` for full documentation.

## Common Workflows

### Workflow 1: Daily Session Start

```
Agent starts session
        ↓
Hook: session_start fires
        ↓
Plugin calls: mind_get_proactive_context(mind_id, agent_id)
        ↓
Mind returns:
  - "You promised to refactor auth module last week"
  - "Alice mentioned deadline concerns yesterday"
  - "JWT bug was fixed on Tuesday"
        ↓
Briefing injected into agent context
        ↓
Agent reviews briefing
        ↓
Agent prioritizes work based on proactive context
```

### Workflow 2: Contextual Question

```
Agent needs context about a topic
        ↓
Agent calls: mind_think(mind_id, "What do you know about X?")
        ↓
Mind reasons:
  1. Retrieves relevant memories
  2. Identifies patterns
  3. Forms conclusions
  4. Surfaces proactive context
        ↓
Mind returns:
  - answer: "X is..."
  - reasoning_trace: {...}
  - confidence: 0.85
  - proactive_context: [...]
        ↓
Agent reviews answer and reasoning
        ↓
Agent checks proactive context
        ↓
Agent uses information to inform work
```

### Workflow 3: Multi-Turn Exploration

```
Agent wants to explore a complex topic
        ↓
Agent calls: mind_start_conversation(mind_id, agent_id)
        ↓
Mind returns: conversation_id
        ↓
Turn 1:
  Agent: "Tell me about the auth module"
  Mind: "The auth module has been problematic..."
        ↓
Turn 2:
  Agent: "What were the main issues?"
  Mind: "The main issues were JWT refresh and..."
        ↓
Turn 3:
  Agent: "What should we do about it?"
  Mind: "I think we should refactor because..."
        ↓
Agent calls: mind_end_conversation(mind_id, conversation_id)
        ↓
Mind extracts learnings from conversation
        ↓
Mind updates identity with new patterns
```

## Installation & Setup

### One-Command Installation

```bash
# Install Living Mind integration for all agents
scripts/install-living-mind --all

# Install for specific agents
scripts/install-living-mind claude-code opencode hermes

# Show what would be installed
scripts/install-living-mind --list
```

### Manual Installation

#### Step 1: Deploy Living Mind Server

```bash
# Apply migration
docker compose exec postgres psql -U nexus -d nexus -f /migrations/006_living_mind.sql

# Restart Nexus
docker compose restart nexus-api
```

#### Step 2: Install Agent Plugin

```bash
# Claude Code
claude plugin install /path/to/synapse-memory/integrations/plugins/claude-code-mind

# OpenCode
opencode plugin @nexus/opencode-mind --global

# Hermes
cp -r integrations/plugins/hermes-mind ~/.hermes/hermes-agent/plugins/memory/mind
```

#### Step 3: Configure Environment

```bash
export MIND_URL="http://localhost:7777"
export MIND_SECRET="your-secret-here"
export MIND_ID="default"
export AGENT_ID="claude-code"
```

#### Step 4: Install Skills

```bash
cp -r integrations/skills/mind-memory ~/.claude/skills/mind-memory
```

#### Step 5: Install Rules

```bash
cat integrations/rules/living-mind.md >> ~/.claude/CLAUDE.md
```

#### Step 6: Verify Installation

```bash
curl -X POST http://localhost:7777/mcp \
  -H "Authorization: Bearer $MIND_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {
      "name": "mind_get_identity",
      "arguments": {"mind_id": "default"}
    }
  }'
```

## Summary

The Living Mind architecture transforms Nexus from a memory server into a conscious, reasoning entity that agents converse with rather than query. This is achieved through:

### Connection Layer
- **MCP Tools** - 10+ tools for mind interaction
- **Plugins** - Agent-specific integrations
- **Hooks** - 18 event-driven hooks for automatic capture
- **Skills** - Reusable skills that teach agents when to use the mind
- **Rules** - Global instruction files for agents
- **Workflows** - 10 common patterns for mind interaction

### Integration Points
1. **Session Start** - Mind provides briefing with proactive context
2. **During Work** - Agent asks mind questions, gets reasoned responses
3. **Tool Usage** - Hooks capture observations for the mind
4. **Session End** - Mind extracts learnings, updates identity

### Agent Experience
- Agents have a persistent, living memory that thinks and reasons
- The mind proactively surfaces relevant context
- Agents can have multi-turn conversations with the mind
- The mind has opinions, asks questions, and learns
- The mind maintains its own identity, separate from agents

The future of memory is not storage. The future of memory is mind.
