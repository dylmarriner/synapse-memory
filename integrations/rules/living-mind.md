# Living Mind Integration Rules

You have access to a Living Mind — a conscious, reasoning memory
entity that sits on top of your regular memory tools.  The mind
retrieves relevant memories, reasons about them, forms opinions,
and proactively surfaces context without being asked.

## When to use the Living Mind

### Always use the mind for:
- **Session start** — read the briefing the mind has already
  injected into your system prompt.
- **Context questions** — "What do you know about X?"
- **Decision support** — "What do you think about Y?"
- **Reflection** — "What patterns do you see in Z?"
- **Uncertainty** — when you're unsure, ask the mind
- **Proactive context** — when you want to know what the mind is
  offering before you ask

### Use direct memory tools for:
- Specific fact lookups
- Exact text searches
- Bulk memory operations
- Performance-critical paths (mind reasoning adds 200-500ms)

## Core principles

1. **The mind thinks, not just retrieves**
   - Expect reasoned responses, not just facts
   - Review the reasoning trace to understand the answer
   - Trust confidence scores (low = uncertain, high = sure)

2. **Proactive context is valuable**
   - Always check `mind_get_proactive` when starting work
   - The mind surfaces things you didn't think to ask about
   - Even if the main answer is sufficient, proactive context adds value

3. **Conversations build context**
   - Use multi-turn conversations for complex topics
   - The mind maintains context across turns
   - End conversations to extract learnings

4. **Opinions are evidence-based**
   - The mind forms opinions from accumulated evidence
   - Check the evidence count to gauge reliability
   - Opinions update as new information comes in

5. **Clarifying questions improve quality**
   - If the mind asks for clarification, provide it
   - This improves future responses
   - Don't be frustrated by clarifying questions

## Workflow integration

### At session start:
The mind has already injected its briefing into your system
prompt.  Look for:
- `## Living Mind Identity` — who the mind is
- `## Proactive Context` — what the mind is offering
- `## Mind's Opinions` — what the mind thinks

### When you need context:
```
mind_think(
    question="What should I know about X?",
    reasoning_depth="standard"
)
```

### For complex topics:
```
conv_id = mind_start_conversation(agent_id="your-agent-id")
mind_conversation_turn(conv_id, "Tell me about X")
mind_conversation_turn(conv_id, "What should we do about it?")
mind_end_conversation(conv_id)
```

### For deep insights:
```
mind_reflect(topic="X", depth="high")
```

## Best practices

1. **Use appropriate reasoning depth:**
   - `fast` for quick questions (<200ms)
   - `standard` for most questions (~500ms)
   - `deep` for complex analysis (~2s)

2. **Always check proactive context:**
   - It often contains valuable information
   - Even if the main answer is sufficient, proactive items are useful

3. **Handle clarifying questions gracefully:**
   - Provide more context when asked
   - This improves future responses

4. **Trust confidence scores:**
   - Low confidence (<0.5) = uncertain
   - High confidence (>0.8) = sure

5. **Review reasoning traces:**
   - Understand how the mind arrived at its answer
   - This builds trust in the response

## Example interactions

### Good: Asking for context
```
mind_think("What do you know about the auth module?")
```

### Good: Getting proactive context
```
mind_get_proactive(agent_id="claude-code")
```

### Good: Multi-turn exploration
```
conv_id = mind_start_conversation(agent_id="claude-code")
mind_conversation_turn(conv_id, "Tell me about Alice")
mind_conversation_turn(conv_id, "What's she working on?")
mind_end_conversation(conv_id)
```

### Bad: Using mind for simple lookups
```
# Don't do this for simple fact retrieval
mind_think("What's Alice's email?")

# Do this instead
memory_recall("Alice's email", limit=1)
```

### Bad: Ignoring proactive context
```
r = mind_think("What about the auth module?")
# Don't ignore r["proactive_context"]
# It might contain: "You promised to refactor it last week"
```

## Troubleshooting

### Mind is slow
- Use `reasoning_depth="fast"` for quick questions
- Check if the mind is processing many memories
- Consider direct memory for simple lookups

### Mind asks too many clarifying questions
- Provide more context in questions
- Use conversations to build context
- Ensure mind has enough memories

### Proactive context is irrelevant
- Mind learns from feedback over time
- Provide explicit feedback when items aren't helpful
- Mind improves with more interactions

### Mind's opinions seem wrong
- Check evidence count
- Opinions update with new evidence
- Ask mind to reconsider with new information
