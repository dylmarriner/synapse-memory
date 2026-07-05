---
name: mind-memory
description: |
  Use the Living Mind for reasoned memory access, proactive context, and
  multi-turn conversations. The mind is a reasoning layer on top of the
  memory store — it retrieves relevant memories, reasons about them,
  forms opinions, and proactively surfaces context without being asked.
triggers:
  - mind
  - living mind
  - remember what
  - what do you know
  - what do you think
  - reflect on
  - my opinion
  - conversation
  - proactive
---

# Living Mind Memory Skill

The Living Mind is a conscious, reasoning memory entity.  Use it
when you need more than a simple memory lookup — when you need
the *mind's perspective*.

## When to use the Living Mind

### Use the mind when:
- You want context about a person, project, or topic
- You want the mind's opinion on a decision
- You want to reflect deeply on past work
- You're starting a new session and want a briefing
- You want to have a multi-turn conversation about something
- You're unsure and want the mind to ask back

### Use direct memory tools when:
- You need a specific fact quickly
- You're searching for exact text
- You're doing bulk memory operations
- Performance matters (mind reasoning adds 200-500ms)

## Available tools

### `mind_think`
Ask the mind a question.  Gets a reasoned answer with confidence,
proactive context, and opinions.

```
mind_think(
    question="What do you know about the auth module?",
    reasoning_depth="standard"  // or "fast" or "deep"
)
```

**Returns**: answer, confidence, memories_cited, proactive_context,
opinions_expressed, reasoning_trace.

### `mind_reflect`
Deep reflection on a topic.  Synthesises many memories into a
single coherent narrative.

```
mind_reflect(topic="auth module health", depth="mid")
```

### `mind_get_proactive`
Get proactive context the mind thinks is relevant — without
asking a question.  Use this to see what the mind is offering.

```
mind_get_proactive(agent_id="claude-code")
```

### `mind_get_identity`
Get the mind's self-model — what it knows about itself, what
it has learned, what it is good at.

### `mind_get_opinions`
Get the mind's opinions.  Optionally filter by topic.

```
mind_get_opinions(topic="auth_module")
```

### `mind_start_conversation` / `mind_conversation_turn` / `mind_end_conversation`
Multi-turn dialogue.  The mind maintains context across turns.

```
conv_id = mind_start_conversation(agent_id="claude-code")
r1 = mind_conversation_turn(conversation_id=conv_id, message="Tell me about Alice")
r2 = mind_conversation_turn(conversation_id=conv_id, message="What's she working on?")
result = mind_end_conversation(conversation_id=conv_id)
// → {learnings_extracted: 3, insights: [...]}
```

## Workflows

### Session start briefing
The mind's briefing is automatically injected into your system
prompt at session start (via the SessionStart hook).  You should
see a `## Living Mind Identity` section with the mind's identity,
proactive context, and opinions.

### Just-in-time context
Before starting a task, ask the mind for context:

```
r = mind_think(
    question="What should I know about refactoring the auth module?",
    reasoning_depth="standard"
)
```

The mind returns its reasoned answer plus any proactive items it
thinks are relevant.

### Decision support
When making a decision, ask the mind for its opinion:

```
r = mind_think(
    question="Should we refactor the auth module or just fix the bugs?"
)
opinion = mind_get_opinions(topic="auth_module")
```

The mind's opinion is based on accumulated evidence — it has
strength, stance, and a count of supporting memories.

### Deep reflection
For complex topics, use `mind_reflect` to get a narrative
synthesis:

```
r = mind_reflect(topic="our development process over the last 6 months")
```

The mind pulls together all relevant memories and produces a
single coherent reflection.

### Multi-turn exploration
For exploratory conversations, use the conversation API:

```
conv_id = mind_start_conversation(agent_id="claude-code")
mind_conversation_turn(conv_id, "What did we work on last week?")
mind_conversation_turn(conv_id, "What were the main challenges?")
mind_conversation_turn(conv_id, "What should we focus on next?")
mind_end_conversation(conv_id)
```

## Best practices

1. **Use appropriate reasoning depth:**
   - `fast` for quick questions (<200ms)
   - `standard` for most questions (~500ms)
   - `deep` for complex analysis (~2s)

2. **Always check proactive context:**
   - The mind often surfaces things you didn't think to ask about
   - Even if the main answer is sufficient, proactive context adds value

3. **Handle clarifying questions:**
   - If the mind asks back, provide more context
   - This improves future responses

4. **Trust confidence scores:**
   - Low confidence (<0.5) = uncertain
   - High confidence (>0.8) = sure

5. **Use conversations for exploration:**
   - Multi-turn conversations are great for complex topics
   - The mind maintains context across turns

6. **Review the reasoning trace:**
   - Understand how the mind arrived at its answer
   - This builds trust in the response
