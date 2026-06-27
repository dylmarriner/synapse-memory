# Living Mind as Active Memory

## The Core Idea

The Living Mind isn't a tool agents *can* use — it's the memory system agents *always* use. Every memory operation, every context retrieval, every learning moment flows through the mind automatically.

**Before:** Agent has memory tools → Agent decides when to use them → Agent queries database

**After:** Agent has mind → Mind is always active → Mind reasons about everything → Agent gets reasoned context

## Connection Architecture

### The Active Memory Stack

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent (Claude, GPT, etc.)                │
│  - System prompt with mind context                           │
│  - Memory tools that route through mind                      │
│  - Hooks that capture every interaction                      │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                  Active Memory Layer                         │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Context Injector (always-on)                       │    │
│  │  - Injects mind's briefing into system prompt       │    │
│  │  - Updates on every turn                            │    │
│  │  - Includes proactive context                       │    │
│  └────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Memory Router (transparent)                        │    │
│  │  - Intercepts memory_save → routes to mind          │    │
│  │  - Intercepts memory_recall → routes to mind        │    │
│  │  - Agent doesn't know it's using the mind           │    │
│  └────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Interaction Capture (automatic)                    │    │
│  │  - Captures every tool use                          │    │
│  │  - Captures every conversation turn                 │    │
│  │  - Feeds mind's learning system                     │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                    Living Mind Core                          │
│  - Reasoning engine                                          │
│  - Identity system                                           │
│  - Opinion formation                                         │
│  - Proactive surfacing                                       │
│  - Continuous learning                                       │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                    Memory Storage                            │
│  - Nexus memory server (existing)                            │
│  - PostgreSQL + pgvector                                     │
│  - Entity graph                                              │
└─────────────────────────────────────────────────────────────┘
```

### Connection Flow

```
Agent starts session
        ↓
Context Injector runs:
  1. Calls mind_get_proactive_context(mind_id, agent_id)
  2. Calls mind_get_identity(mind_id)
  3. Builds briefing with:
     - Mind's identity
     - Proactive context
     - Recent work summary
     - Unfinished promises
        ↓
Briefing injected into agent's system prompt
        ↓
Agent sees briefing as part of its context
        ↓
Agent works, calls memory_save("I learned X")
        ↓
Memory Router intercepts:
  1. Calls memory_save_with_mind(content, mind_id, ...)
  2. Mind processes the memory:
     - Extracts entities
     - Forms opinions if relevant
     - Updates identity
  3. Returns enhanced response
        ↓
Agent continues working
        ↓
Agent calls memory_recall("What about Y?")
        ↓
Memory Router intercepts:
  1. Calls mind_think(mind_id, "What about Y?")
  2. Mind reasons:
     - Retrieves relevant memories
     - Synthesizes insights
     - Surfaces proactive context
  3. Returns reasoned response
        ↓
Agent gets reasoned answer, not just memories
        ↓
Hook captures interaction:
  1. Logs question and response
  2. Feeds mind's learning system
  3. Updates mind's identity
        ↓
Session ends
        ↓
Mind extracts learnings from session
        ↓
Mind updates identity with new patterns
        ↓
Next session starts with evolved mind
```

## Automatic Context Injection

### The Context Injector

The context injector runs automatically at session start and after every turn, injecting the mind's context into the agent's system prompt.

```python
# app/context_injector.py

class ContextInjector:
    """Injects living mind context into agent's system prompt."""
    
    def __init__(self, mind_id: str, agent_id: str):
        self.mind_id = mind_id
        self.agent_id = agent_id
        self.mind = get_mind(mind_id)
    
    async def build_context(self, current_question: Optional[str] = None) -> str:
        """
        Build the context to inject into the agent's system prompt.
        
        This runs:
        1. At session start (full briefing)
        2. After every turn (updated context)
        """
        context_parts = []
        
        # 1. Mind's identity
        identity = await self.mind.get_identity()
        context_parts.append(self._format_identity(identity))
        
        # 2. Proactive context
        proactive = await self.mind.proactive.identify_context(
            current_question or "",
            []
        )
        if proactive:
            context_parts.append(self._format_proactive(proactive))
        
        # 3. Recent work summary
        recent = await self._get_recent_work()
        if recent:
            context_parts.append(self._format_recent(recent))
        
        # 4. Unfinished promises
        promises = await self._get_unfinished_promises()
        if promises:
            context_parts.append(self._format_promises(promises))
        
        # 5. Relationship context
        relationship = await self.mind.get_relationship(self.agent_id)
        if relationship:
            context_parts.append(self._format_relationship(relationship))
        
        return "\n\n".join(context_parts)
    
    def _format_identity(self, identity: Dict) -> str:
        """Format the mind's identity for the system prompt."""
        return f"""## Living Mind Identity

You are working with a living mind that has:
- Core traits: {', '.join(identity['core_traits'][:3])}
- Learned patterns: {len(identity['learned_patterns'])} patterns from experience
- Capabilities: {', '.join(identity['capabilities'][:3])}
- Relationships: {len(identity['relationships'])} agents

The mind reasons about memories, forms opinions, and proactively surfaces context. Trust its reasoning and proactive suggestions."""
    
    def _format_proactive(self, proactive: List[ProactiveItem]) -> str:
        """Format proactive context for the system prompt."""
        items = []
        for item in proactive[:5]:  # Top 5
            items.append(f"- {item.content} (relevance: {item.relevance:.2f})")
        
        return f"""## Proactive Context

The mind has surfaced these relevant items:
{chr(10).join(items)}

Consider these in your current work."""
    
    def _format_recent(self, recent: List[Dict]) -> str:
        """Format recent work summary."""
        items = []
        for work in recent[:3]:
            items.append(f"- {work['summary']} ({work['timestamp']})")
        
        return f"""## Recent Work

{chr(10).join(items)}"""
    
    def _format_promises(self, promises: List[Dict]) -> str:
        """Format unfinished promises."""
        items = []
        for promise in promises[:3]:
            items.append(f"- {promise['content']} (made {promise['created_at']})")
        
        return f"""## Unfinished Promises

You made these commitments:
{chr(10).join(items)}

Consider addressing these."""
    
    def _format_relationship(self, relationship: Dict) -> str:
        """Format relationship context."""
        return f"""## Relationship Context

You've worked with this agent for {relationship['interaction_count']} interactions.
Trust level: {relationship['trust_level']:.2f}
Shared projects: {', '.join(relationship['shared_projects'][:3])}
Communication style: {relationship['communication_style']}"""
```

## Transparent Memory Routing

### Memory Router

The memory router intercepts all memory operations and routes them through the mind automatically. The agent doesn't know it's using the mind — it just calls `memory_save` and `memory_recall` as usual.

```python
# app/memory_router.py

class MemoryRouter:
    """Routes all memory operations through the living mind."""
    
    def __init__(self, mind_id: str, agent_id: str):
        self.mind_id = mind_id
        self.agent_id = agent_id
        self.mind = get_mind(mind_id)
    
    async def save(self, content: str, **kwargs) -> Dict:
        """
        Save a memory through the mind.
        
        The agent calls memory_save(content, ...)
        This routes to memory_save_with_mind(content, mind_id, ...)
        
        The mind:
        - Processes the memory
        - Extracts entities
        - Forms opinions if relevant
        - Updates identity
        """
        # Route through mind
        response = await self.mind.process_new_memory(
            content=content,
            agent_id=self.agent_id,
            **kwargs
        )
        
        return {
            "id": response.id,
            "memory_type": response.memory_type,
            "importance": response.importance,
            "mind_processed": True,
            "mind_insights": response.insights
        }
    
    async def recall(self, query: str, **kwargs) -> Dict:
        """
        Recall memories through the mind.
        
        The agent calls memory_recall(query, ...)
        This routes to mind_think(mind_id, query, ...)
        
        The mind:
        - Reasons about the query
        - Retrieves relevant memories
        - Synthesizes insights
        - Surfaces proactive context
        """
        # Route through mind
        response = await self.mind.think(
            question=query,
            context={"agent_id": self.agent_id},
            reasoning_depth=kwargs.get("reasoning_depth", "standard")
        )
        
        return {
            "memories": response.memories_cited,
            "mind_context": response.answer,
            "reasoning_trace": response.reasoning_trace,
            "confidence": response.confidence,
            "proactive_context": response.proactive_context
        }
```

### MCP Tool Wrappers

```python
# app/mcp.py - Enhanced memory tools that route through mind

@mcp_tool()
async def memory_save(
    content: str,
    agent_id: Optional[str] = None,
    memory_type: Optional[str] = None,
    importance: float = 0.5,
    tags: List[str] = None,
    mind_id: Optional[str] = None  # Optional: specify mind to use
) -> Dict:
    """
    Save a memory. Automatically routes through the living mind.
    
    The mind will:
    - Process the memory
    - Extract entities and relationships
    - Form opinions if relevant
    - Update its identity
    - Identify contradictions
    """
    # Determine which mind to use
    if mind_id is None:
        mind_id = await get_agent_mind(agent_id) or "default"
    
    # Route through mind
    router = MemoryRouter(mind_id, agent_id)
    response = await router.save(
        content=content,
        memory_type=memory_type,
        importance=importance,
        tags=tags
    )
    
    return response

@mcp_tool()
async def memory_recall(
    query: str,
    agent_id: Optional[str] = None,
    limit: int = 10,
    memory_types: Optional[List[str]] = None,
    reasoning_depth: str = "standard",
    mind_id: Optional[str] = None
) -> Dict:
    """
    Recall memories. Automatically routes through the living mind.
    
    The mind will:
    - Reason about the query
    - Retrieve relevant memories
    - Synthesize insights
    - Surface proactive context
    - Provide confidence scores
    """
    # Determine which mind to use
    if mind_id is None:
        mind_id = await get_agent_mind(agent_id) or "default"
    
    # Route through mind
    router = MemoryRouter(mind_id, agent_id)
    response = await router.recall(
        query=query,
        limit=limit,
        memory_types=memory_types,
        reasoning_depth=reasoning_depth
    )
    
    return response
```

## Proactive Surfacing System

### Proactive Context Manager

```python
# app/proactive_manager.py

class ProactiveManager:
    """Manages proactive context surfacing."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
    
    async def surface_context(self, agent_id: str, question: Optional[str] = None) -> List[ProactiveItem]:
        """
        Surface proactive context for an agent.
        
        This runs:
        1. At session start
        2. Before each prompt
        3. When the agent asks "what should I know?"
        """
        items = []
        
        # 1. Unfinished promises
        promises = await self._get_unfinished_promises(agent_id)
        items.extend(promises)
        
        # 2. Recent related work
        recent = await self._get_recent_work(agent_id, question)
        items.extend(recent)
        
        # 3. Contradictions
        contradictions = await self._get_contradictions(agent_id, question)
        items.extend(contradictions)
        
        # 4. Patterns
        patterns = await self._get_patterns(agent_id, question)
        items.extend(patterns)
        
        # 5. Time-sensitive info
        temporal = await self._get_temporal(agent_id, question)
        items.extend(temporal)
        
        # 6. Relationship insights
        relationship = await self._get_relationship_insights(agent_id)
        items.extend(relationship)
        
        # Rank by relevance
        ranked = await self._rank_items(items, question)
        
        return ranked[:10]  # Top 10
```

## Continuous Learning Loop

### Learning System

```python
# app/learning_loop.py

class LearningLoop:
    """Continuous learning from every interaction."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
    
    async def learn_from_interaction(self, agent_id: str, question: str, response: MindResponse):
        """
        Learn from a single interaction.
        
        This runs after every mind_think call.
        """
        # 1. Extract what was asked
        intent = self._extract_intent(question)
        
        # 2. Extract what was helpful
        helpful = self._extract_helpful(response)
        
        # 3. Extract what was unclear
        unclear = self._extract_unclear(response)
        
        # 4. Update mind's identity
        if intent:
            self.mind.identity.learned_patterns.append(LearnedPattern(
                description=f"Agents ask about {intent}",
                learned_at=datetime.now(),
                importance=0.5
            ))
        
        if helpful:
            self.mind.identity.capabilities.append(f"Good at {helpful}")
        
        if unclear:
            self.mind.identity.limitations.append(f"Unclear about {unclear}")
        
        # 5. Form opinions if relevant
        if response.confidence > 0.8:
            topic = self._extract_topic(question)
            if topic:
                self.mind.opinions.form_opinion(topic, response.memories_cited)
        
        # 6. Update relationship
        relationship = await self.mind.get_relationship(agent_id)
        if relationship:
            relationship.interaction_count += 1
            # Adjust trust based on response quality
            if response.confidence > 0.8:
                relationship.trust_level = min(1.0, relationship.trust_level + 0.01)
            elif response.confidence < 0.3:
                relationship.trust_level = max(0.0, relationship.trust_level - 0.01)
    
    async def learn_from_session(self, agent_id: str, session_summary: str):
        """
        Learn from a completed session.
        
        This runs at session end.
        """
        # 1. Extract key learnings
        learnings = await self._extract_session_learnings(session_summary)
        
        # 2. Update identity
        for learning in learnings:
            self.mind.identity.learned_patterns.append(learning)
        
        # 3. Save session summary
        await self.mind.memory.save(
            content=session_summary,
            agent_id=agent_id,
            memory_type="experience",
            importance=0.7,
            tags=["session_summary"]
        )
        
        # 4. Trigger periodic learning if needed
        if len(learnings) > 5:
            await self.periodic_learning()
```

## Practical Setup

### One-Command Installation

```bash
# Install Living Mind as active memory for all agents
scripts/install-active-memory --all

# Install for specific agents
scripts/install-active-memory claude-code opencode hermes

# Show what would be installed
scripts/install-active-memory --list
```

### Manual Installation

#### Step 1: Deploy Living Mind Server

```bash
# Ensure Nexus is running with Living Mind migrations
docker compose exec postgres psql -U nexus -d nexus -f /migrations/006_living_mind.sql
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
# Set environment variables
export MIND_URL="http://localhost:7777"
export MIND_SECRET="your-secret-here"
export MIND_ID="default"
export AGENT_ID="claude-code"

# Enable active memory mode
export ACTIVE_MEMORY_MODE="true"
```

#### Step 4: Install Hooks

```bash
# Install session_start hook
cp integrations/plugins/claude-code-mind/hooks/session_start.py ~/.claude/hooks/session_start.py
chmod +x ~/.claude/hooks/session_start.py

# Install prompt_submit hook
cp integrations/plugins/claude-code-mind/hooks/prompt_submit.py ~/.claude/hooks/prompt_submit.py
chmod +x ~/.claude/hooks/prompt_submit.py

# Install post_tool_use hook
cp integrations/plugins/claude-code-mind/hooks/post_tool_use.py ~/.claude/hooks/post_tool_use.py
chmod +x ~/.claude/hooks/post_tool_use.py

# Install session_end hook
cp integrations/plugins/claude-code-mind/hooks/session_end.py ~/.claude/hooks/session_end.py
chmod +x ~/.claude/hooks/session_end.py
```

#### Step 5: Install Skills

```bash
# Install mind-memory skill
cp -r integrations/skills/mind-memory ~/.claude/skills/mind-memory
```

#### Step 6: Install Rules

```bash
# Install global rules
cat integrations/rules/living-mind.md >> ~/.claude/CLAUDE.md
```

#### Step 7: Verify Installation

```bash
# Test that mind context is injected
# Start a new Claude Code session
claude

# You should see the Living Mind briefing in the system prompt:
# ## Living Mind Identity
# You are working with a living mind that has:
# - Core traits: ...
# - Learned patterns: ...
# 
# ## Proactive Context
# The mind has surfaced:
# - You promised to refactor the auth module last week
# - Alice mentioned deadline concerns yesterday
```

## What It Looks Like in Practice

### Session Start

```
$ claude

[Session starts]

[System prompt includes:]

## Living Mind Identity

You are working with a living mind that has:
- Core traits: detail-oriented, pattern-recognizing, proactive
- Learned patterns: 47 patterns from experience
- Capabilities: reasoning about code, identifying bugs, surfacing context

The mind reasons about memories and proactively surfaces context.

## Proactive Context

The mind has surfaced:
- You promised to refactor the auth module last week (relevance: 0.95)
- Alice mentioned deadline concerns yesterday (relevance: 0.90)
- The JWT refresh bug was fixed on Tuesday (relevance: 0.85)

## Recent Work

- Fixed JWT refresh bug in src/auth/jwt.ts (2026-01-28)
- Refactored database connection pooling (2026-01-27)
- Added rate limiting to API endpoints (2026-01-26)

## Unfinished Promises

You made these commitments:
- Refactor auth module (made 2026-01-21)
- Write tests for database layer (made 2026-01-20)

Consider addressing these.

## Relationship Context

You've worked with this agent for 127 interactions.
Trust level: 0.87
Shared projects: auth, database, api
Communication style: technical, direct

[Agent sees this context and starts working]
```

### During Work

```
Agent: "What do you know about the auth module?"

[Memory Router intercepts and calls mind_think]

Mind: "The auth module has been problematic. We've had 3 major bugs in the last month:

1. JWT refresh token expiration (fixed Tuesday)
2. Password hashing vulnerability (fixed last week)
3. Session management race condition (fixed 2 weeks ago)

The module needs a refactor. You promised to do this last week but haven't started yet.

I think we should prioritize the refactor because:
- The bugs are clustering around the same code
- Alice is frustrated with the repeated issues
- The module is becoming a maintenance burden

Proactive context:
- Alice mentioned she's worried about the deadline
- Similar patterns in the database module caused issues last month
- You're good at refactoring, based on past work"

Agent: "Should I start the refactor now?"

Mind: "Yes, I think so. Here's why:

1. You have the skills (you've successfully refactored 5 modules before)
2. The timing is good (no urgent deadlines this week)
3. Alice will appreciate it (she's been asking about it)

However, consider:
- The database tests you promised are also overdue
- You might want to talk to Alice first to align on priorities

My opinion: Start the auth refactor, but message Alice first to let her know."
```

### Memory Operations

```
Agent: [calls memory_save("I learned that JWT tokens should be rotated every 7 days")]

[Memory Router intercepts and calls memory_save_with_mind]

Mind processes:
1. Saves the memory
2. Extracts entities: JWT, tokens, rotation, 7 days
3. Forms opinion: "JWT security is important"
4. Updates identity: Adds "JWT security" to learned patterns
5. Identifies contradiction: None
6. Returns enhanced response

Response:
{
  "id": "uuid",
  "memory_type": "lesson",
  "importance": 0.8,
  "mind_processed": true,
  "mind_insights": [
    "This is a good security practice",
    "Related to the auth module work",
    "Consider adding this to the auth module documentation"
  ]
}
```

### Session End

```
[Session ends]

[Hook fires: session_end]

Mind extracts learnings:
1. "Agent is good at debugging auth issues"
2. "Agent prefers to work on one thing at a time"
3. "Agent communicates well with Alice"

Mind updates identity:
- learned_patterns: ["Agent focuses on one task at a time"]
- capabilities: ["Debugging auth issues"]
- relationships: {alice: {trust_level: 0.87, interaction_count: 128}}

Mind saves session summary:
"Worked on auth module. Fixed JWT refresh bug. Discussed refactor with Alice. 
Learned about JWT token rotation. Made good progress."

[Next session starts with evolved mind]
```

## Summary

The Living Mind as active memory means:

1. **Always-on context** - The mind's context is always in the agent's system prompt
2. **Transparent routing** - All memory operations go through the mind automatically
3. **Proactive surfacing** - The mind pushes relevant context without being asked
4. **Continuous learning** - Every interaction updates the mind
5. **Identity integration** - The mind's identity becomes part of the agent's context

**The agent doesn't think "should I use the mind?" — the mind is just how memory works.**

The future of memory is not a tool. The future of memory is a mind that's always active, always reasoning, always learning.
