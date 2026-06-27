# Living Mind Architecture

## Overview

The Living Mind transforms Nexus from a memory retrieval server into a conscious, reasoning entity that agents converse with rather than query. The Living Mind has opinions, asks questions, reflects on memories, and maintains its own identity separate from the agents it serves.

**Core Principle:** Memory is not a database. Memory is a mind.

## Vision & Goals

### What We're Building
A persistent, reasoning memory entity that:
- **Thinks** about memories, not just retrieves them
- **Converses** with agents, not just responds to queries
- **Has opinions** based on accumulated experience
- **Asks questions** when context is unclear
- **Learns** patterns and insights over time
- **Maintains identity** separate from agents
- **Proactively surfaces** relevant context

### Success Criteria
1. Agents can have multi-turn conversations with the mind
2. The mind provides reasoning, not just facts
3. The mind can express uncertainty and ask for clarification
4. The mind maintains a coherent self-model
5. The mind proactively offers insights without being asked
6. Memory retrieval is contextualized by the mind's reasoning

## Architecture Overview

### System Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Layer                               │
│  (Your coding agents: Claude, GPT, etc.)                    │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│                 Conversation Layer                           │
│  - Dialogue management                                       │
│  - Context tracking                                          │
│  - Turn-taking                                               │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│                   Living Mind Layer                          │
│  - Reasoning engine                                          │
│  - Opinion formation                                         │
│  - Self-model                                                │
│  - Proactive surfacing                                       │
│  - Learning & adaptation                                     │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│                   Memory Layer                               │
│  - Memory storage (existing Nexus)                           │
│  - Retrieval (existing 4-mode fused search)                  │
│  - Consolidation (existing)                                  │
│  - NEW: Provenance tracking                                  │
│  - NEW: Confidence scoring                                   │
└─────────────────────────────────────────────────────────────┘
```

### Component Interaction

```
Agent asks question
        ↓
Conversation Layer receives
        ↓
Living Mind reasons:
  1. What is being asked?
  2. What do I know? (retrieve memories)
  3. What do I think? (form opinion)
  4. Do I need clarification? (ask back)
  5. What's relevant proactively? (surface context)
        ↓
Conversation Layer formats response
        ↓
Agent receives reasoned answer
```

## Core Components

### 1. Living Mind Agent (`app/mind/living_mind.py`)

The central reasoning entity.

```python
class LivingMind:
    """A conscious memory entity that reasons about memories."""
    
    def __init__(self, mind_id: str, config: MindConfig):
        self.mind_id = mind_id
        self.config = config
        self.llm = self._init_llm()
        self.memory = self._init_memory()
        self.identity = self._init_identity()
        self.conversation_history = []
        
    def think(self, question: str, context: Optional[Dict] = None) -> MindResponse:
        """
        Process a question through the reasoning pipeline.
        
        Returns: MindResponse with answer, confidence, reasoning_trace, 
                 proactive_context, and optional clarifying_question
        """
        # 1. Understand the question
        understanding = self._understand_question(question, context)
        
        # 2. Retrieve relevant memories
        memories = self._retrieve_memories(understanding)
        
        # 3. Check if clarification needed
        if self._needs_clarification(question, memories):
            clarifying_q = self._form_clarifying_question(question, memories)
            return MindResponse(
                answer=None,
                clarifying_question=clarifying_q,
                confidence=0.0
            )
        
        # 4. Reason about memories
        reasoning = self._reason_about_memories(question, memories)
        
        # 5. Form opinion
        opinion = self._form_opinion(reasoning)
        
        # 6. Identify proactive context
        proactive = self._identify_proactive_context(question, memories)
        
        # 7. Compose response
        answer = self._compose_answer(question, reasoning, opinion, proactive)
        
        return MindResponse(
            answer=answer,
            reasoning_trace=reasoning,
            confidence=reasoning.confidence,
            proactive_context=proactive,
            memories_cited=memories
        )
```

### 2. Reasoning Engine (`app/mind/reasoning.py`)

Handles the cognitive process of thinking about memories.

```python
class ReasoningEngine:
    """Multi-step reasoning over memories."""
    
    def reason(self, question: str, memories: List[Memory], 
               identity: Identity) -> ReasoningResult:
        """
        Reasoning pipeline:
        1. Analyze question intent
        2. Evaluate memory relevance
        3. Identify patterns and connections
        4. Synthesize insights
        5. Form conclusions
        6. Assess confidence
        """
        
        # Step 1: Question analysis
        intent = self._analyze_intent(question)
        
        # Step 2: Memory evaluation
        relevant = self._evaluate_relevance(memories, intent)
        
        # Step 3: Pattern recognition
        patterns = self._identify_patterns(relevant)
        
        # Step 4: Insight synthesis
        insights = self._synthesize_insights(relevant, patterns)
        
        # Step 5: Conclusion formation
        conclusion = self._form_conclusion(question, insights, identity)
        
        # Step 6: Confidence assessment
        confidence = self._assess_confidence(relevant, conclusion)
        
        return ReasoningResult(
            intent=intent,
            relevant_memories=relevant,
            patterns=patterns,
            insights=insights,
            conclusion=conclusion,
            confidence=confidence,
            reasoning_trace=self._build_trace()
        )
```

### 3. Identity System (`app/mind/identity.py`)

Maintains the mind's self-model.

```python
class Identity:
    """The mind's evolving self-model."""
    
    def __init__(self, mind_id: str):
        self.mind_id = mind_id
        self.core_traits = []  # Stable characteristics
        self.learned_patterns = []  # Discovered patterns
        self.relationships = {}  # agent_id -> Relationship
        self.opinions = {}  # topic -> Opinion
        self.capabilities = []  # What the mind knows it can do
        self.limitations = []  # What the mind knows it can't do
        
    def update_from_interaction(self, interaction: Interaction):
        """Update identity based on conversation."""
        # Learn from what was asked
        # Learn from what was helpful
        # Learn from what was unclear
        # Update opinions based on outcomes
        
    def get_self_description(self) -> str:
        """Generate natural language self-description."""
        return f"""I am a living mind with {len(self.core_traits)} core traits.
        I've learned {len(self.learned_patterns)} patterns from my experiences.
        I have relationships with {len(self.relationships)} agents.
        I have opinions on {len(self.opinions)} topics.
        My strengths: {', '.join(self.capabilities[:3])}
        My limitations: {', '.join(self.limitations[:3])}"""
```

### 4. Conversation Manager (`app/mind/conversation.py`)

Manages dialogue state and context.

```python
class ConversationManager:
    """Manages multi-turn conversations with agents."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
        self.active_conversations = {}  # conversation_id -> ConversationState
        
    def start_conversation(self, agent_id: str) -> str:
        """Start a new conversation, return conversation_id."""
        conv_id = str(uuid.uuid4())
        self.active_conversations[conv_id] = ConversationState(
            agent_id=agent_id,
            turns=[],
            context={},
            started_at=datetime.now()
        )
        return conv_id
    
    def process_turn(self, conv_id: str, agent_message: str) -> MindResponse:
        """Process one turn of conversation."""
        state = self.active_conversations[conv_id]
        
        # Build context from conversation history
        context = self._build_context(state)
        
        # Get mind's response
        response = self.mind.think(agent_message, context)
        
        # Update state
        state.turns.append(Turn(
            agent_message=agent_message,
            mind_response=response,
            timestamp=datetime.now()
        ))
        
        # Update context
        state.context = self._update_context(state.context, response)
        
        return response
    
    def end_conversation(self, conv_id: str):
        """End conversation, extract learnings."""
        state = self.active_conversations[conv_id]
        
        # Extract insights from conversation
        insights = self._extract_insights(state)
        
        # Update mind's identity
        self.mind.identity.update_from_interaction(Interaction(
            agent_id=state.agent_id,
            conversation=state,
            insights=insights
        ))
        
        # Store conversation summary
        self.mind.memory.save(
            content=self._summarize_conversation(state),
            memory_type="experience",
            importance=0.7,
            tags=["conversation", state.agent_id]
        )
        
        del self.active_conversations[conv_id]
```

### 5. Proactive Surfacing (`app/mind/proactive.py`)

Identifies and surfaces relevant context without being asked.

```python
class ProactiveSurfacing:
    """Surfaces relevant context proactively."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
        
    def identify_context(self, question: str, memories: List[Memory]) -> List[ProactiveItem]:
        """
        Identify context that might be relevant but wasn't explicitly asked about.
        
        Triggers:
        - Unfinished promises
        - Recent related work
        - Contradictions with current question
        - Patterns from similar past situations
        - Time-sensitive information
        """
        items = []
        
        # Check for unfinished promises
        promises = self._check_promises(question, memories)
        items.extend(promises)
        
        # Check for recent related work
        recent = self._check_recent_work(question, memories)
        items.extend(recent)
        
        # Check for contradictions
        contradictions = self._check_contradictions(question, memories)
        items.extend(contradictions)
        
        # Check for patterns
        patterns = self._check_patterns(question, memories)
        items.extend(patterns)
        
        # Check for time-sensitive info
        temporal = self._check_temporal(question, memories)
        items.extend(temporal)
        
        # Rank by relevance
        ranked = self._rank_items(items, question)
        
        return ranked[:5]  # Top 5 proactive items
```

### 6. Opinion System (`app/mind/opinions.py`)

Forms and maintains opinions based on accumulated experience.

```python
class OpinionSystem:
    """Forms and maintains opinions based on experience."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
        self.opinions = {}  # topic -> Opinion
        
    def form_opinion(self, topic: str, evidence: List[Memory]) -> Opinion:
        """Form an opinion based on evidence."""
        # Analyze evidence
        positive = self._count_positive(evidence)
        negative = self._count_negative(evidence)
        neutral = self._count_neutral(evidence)
        
        # Form opinion
        if positive > negative * 2:
            stance = "positive"
            strength = min(1.0, positive / (positive + negative + neutral))
        elif negative > positive * 2:
            stance = "negative"
            strength = min(1.0, negative / (positive + negative + neutral))
        else:
            stance = "neutral"
            strength = 0.5
        
        opinion = Opinion(
            topic=topic,
            stance=stance,
            strength=strength,
            evidence_count=len(evidence),
            formed_at=datetime.now(),
            last_updated=datetime.now()
        )
        
        self.opinions[topic] = opinion
        return opinion
    
    def update_opinion(self, topic: str, new_evidence: Memory):
        """Update opinion with new evidence."""
        if topic not in self.opinions:
            self.form_opinion(topic, [new_evidence])
        else:
            opinion = self.opinions[topic]
            # Recalculate based on new evidence
            # ...
            opinion.last_updated = datetime.now()
```

### 7. Learning System (`app/mind/learning.py`)

Extracts patterns and insights over time.

```python
class LearningSystem:
    """Extracts patterns and insights from accumulated experience."""
    
    def __init__(self, mind: LivingMind):
        self.mind = mind
        
    def learn_from_conversation(self, conversation: ConversationState):
        """Extract learnings from a completed conversation."""
        # What was asked?
        # What was helpful?
        # What was unclear?
        # What patterns emerged?
        
        learnings = self._extract_learnings(conversation)
        
        for learning in learnings:
            self.mind.identity.learned_patterns.append(learning)
            self.mind.memory.save(
                content=learning.description,
                memory_type="observation",
                importance=learning.importance,
                tags=["learning", "pattern"]
            )
    
    def periodic_learning(self):
        """Run periodic learning job (e.g., daily)."""
        # Analyze recent conversations
        # Identify recurring patterns
        # Update identity
        # Form new opinions
        # Surface insights
```

## Data Model Changes

### New Tables

```sql
-- Mind identity and self-model
CREATE TABLE minds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    core_traits JSONB NOT NULL DEFAULT '[]',
    learned_patterns JSONB NOT NULL DEFAULT '[]',
    capabilities JSONB NOT NULL DEFAULT '[]',
    limitations JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Mind-agent relationships
CREATE TABLE mind_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id UUID REFERENCES minds(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    trust_level FLOAT NOT NULL DEFAULT 0.5,
    interaction_count INT NOT NULL DEFAULT 0,
    shared_projects JSONB NOT NULL DEFAULT '[]',
    communication_style TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(mind_id, agent_id)
);

-- Mind opinions
CREATE TABLE mind_opinions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id UUID REFERENCES minds(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    stance TEXT NOT NULL,  -- positive, negative, neutral
    strength FLOAT NOT NULL,
    evidence_count INT NOT NULL DEFAULT 0,
    formed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(mind_id, topic)
);

-- Conversation history
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mind_id UUID REFERENCES minds(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    turn_count INT NOT NULL DEFAULT 0,
    summary TEXT,
    insights JSONB NOT NULL DEFAULT '[]',
    metadata JSONB NOT NULL DEFAULT '{}'
);

-- Conversation turns
CREATE TABLE conversation_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number INT NOT NULL,
    agent_message TEXT NOT NULL,
    mind_response JSONB NOT NULL,  -- Full MindResponse
    reasoning_trace JSONB,
    memories_cited UUID[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Memory provenance
ALTER TABLE memories ADD COLUMN mind_id UUID REFERENCES minds(id);
ALTER TABLE memories ADD COLUMN confidence FLOAT DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN source_type TEXT;  -- user_stated, inferred, observed
ALTER TABLE memories ADD COLUMN times_recalled INT DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_recalled TIMESTAMPTZ;
```

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
**Goal:** Basic Living Mind with simple reasoning

- Create `app/mind/` directory structure
- Implement `LivingMind` class with basic `think()` method
- Implement simple `ReasoningEngine` (retrieve → reason → respond)
- Add database migrations for `minds` table
- Create `/v1/mind/think` endpoint
- Basic tests: mind can answer simple questions

**Deliverable:** Agent can ask mind a question and get a reasoned response

### Phase 2: Conversation (Weeks 3-4)
**Goal:** Multi-turn conversations with context tracking

- Implement `ConversationManager`
- Add `conversations` and `conversation_turns` tables
- Create conversation endpoints (`/start`, `/turn`, `/end`)
- Implement context tracking across turns
- Extract learnings from completed conversations
- Tests: multi-turn conversations work correctly

**Deliverable:** Agent can have multi-turn conversations with mind

### Phase 3: Identity & Opinions (Weeks 5-6)
**Goal:** Mind has self-model and can form opinions

- Implement `Identity` system
- Implement `OpinionSystem`
- Add `mind_relationships` and `mind_opinions` tables
- Update identity from interactions
- Form opinions from evidence
- Create `/identity` and `/opinions` endpoints
- Tests: identity evolves, opinions form correctly

**Deliverable:** Mind has evolving identity and can express opinions

### Phase 4: Proactive Surfacing (Weeks 7-8)
**Goal:** Mind proactively offers relevant context

- Implement `ProactiveSurfacing` system
- Identify triggers (promises, recent work, contradictions, patterns)
- Integrate proactive context into `think()` response
- Add proactive items to conversation responses
- Tests: proactive context surfaces correctly

**Deliverable:** Mind proactively offers relevant context

### Phase 5: Learning & Adaptation (Weeks 9-10)
**Goal:** Mind learns from experience

- Implement `LearningSystem`
- Extract patterns from conversations
- Update identity with learned patterns
- Implement periodic learning job
- Add memory provenance tracking
- Tests: mind learns from interactions

**Deliverable:** Mind learns and adapts over time

### Phase 6: Advanced Reasoning (Weeks 11-12)
**Goal:** Sophisticated reasoning capabilities

- Implement clarification questions
- Add uncertainty handling
- Implement reflection endpoint
- Add confidence calibration
- Implement graceful forgetting
- Tests: advanced reasoning works correctly

**Deliverable:** Mind can handle complex reasoning scenarios

### Phase 7: Integration & Polish (Weeks 13-14)
**Goal:** Full integration with existing system

- Integrate mind into agent context building
- Add mind to MCP tools
- Update documentation
- Performance optimization
- Comprehensive testing
- Migration guide for existing users

**Deliverable:** Production-ready Living Mind system

## Technical Decisions

### LLM Selection for Reasoning

**Decision:** Use the same LLM as the agent (configurable)

**Rationale:**
- Consistency in reasoning style
- Can be configured per mind
- Allows for different "personalities"

### Reasoning Depth

**Decision:** Configurable reasoning depth (fast/standard/deep)

**Rationale:**
- Fast: Simple retrieval + minimal reasoning (low latency)
- Standard: Full reasoning pipeline (balanced)
- Deep: Extended reflection and synthesis (high quality)

### Memory Retrieval Strategy

**Decision:** Hybrid retrieval with reasoning-guided filtering

**Rationale:**
- Initial broad retrieval (existing 4-mode search)
- Reasoning engine filters for relevance
- Reduces noise in reasoning

### Conversation State Storage

**Decision:** Store in database, not in-memory

**Rationale:**
- Survives restarts
- Can be analyzed later
- Enables learning from past conversations

### Proactive Context Limits

**Decision:** Max 5 proactive items per response

**Rationale:**
- Prevents information overload
- Keeps responses focused
- Agent can ask for more if needed

### Opinion Formation Threshold

**Decision:** Require 3+ evidence items before forming strong opinion

**Rationale:**
- Prevents premature opinions
- Ensures opinions are evidence-based
- Allows for opinion evolution

## Success Metrics

### Functional Metrics

1. **Conversation Quality**
   - Agents can complete multi-turn conversations
   - Mind provides relevant context proactively
   - Mind asks clarifying questions when needed

2. **Reasoning Quality**
   - Responses include reasoning traces
   - Confidence scores correlate with accuracy
   - Opinions are evidence-based

3. **Learning Effectiveness**
   - Mind extracts learnings from conversations
   - Identity evolves over time
   - Patterns are identified correctly

### Performance Metrics

1. **Response Time**
   - Fast reasoning: <500ms
   - Standard reasoning: <2s
   - Deep reasoning: <5s

2. **Memory Efficiency**
   - Conversation storage: <1KB per turn
   - Identity storage: <10KB per mind
   - Opinion storage: <1KB per opinion

3. **Scalability**
   - Support 100+ concurrent conversations
   - Support 1000+ minds
   - Support 1M+ memories per mind

## Conclusion

The Living Mind architecture transforms Nexus from a memory server into a conscious, reasoning entity. This is not just an incremental improvement — it's a fundamental reimagining of what memory can be.

**Key Principles:**
1. Memory is not a database — it's a mind
2. Agents don't query memory — they converse with it
3. The mind has opinions, asks questions, and learns
4. The mind has its own identity, separate from agents
5. The mind proactively offers context and insights

The future of memory is not storage. The future of memory is mind.
