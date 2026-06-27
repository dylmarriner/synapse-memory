"""Single-pass ADD-only extraction prompts.

These prompts replace a multi-call classify→extract→conclude path with one
LLM call that returns a JSON list of new memories, each carrying its
`memory_type`, `importance`, `tags`, and `linked_memory_ids`.

Key rules baked into the prompts:

1. **ADD-only** — every fact is appended; nothing is overwritten or deleted.
2. **Observation-date anchored** — relative time ("yesterday", "last
   week") resolves against the observation date baked into the prompt, not
   the model's notion of "now", so facts remain meaningful years later.
3. **Linked memories** — when a new fact is related to an existing memory,
   the new fact carries the existing memory's id in `linked_memory_ids`,
   which lets the entity graph form naturally.
4. **No echo extraction** — assistant rephrasings of the user's own words
   are not extracted twice.
5. **No detail contamination** — the prompt explicitly forbids the model
   from importing entity names from existing memories into new extractions.
6. **Empty is better than wrong** — when the user message has no durable
   fact, return `{"memories": []}` rather than hallucinate.

The Nexus-specific `memory_type` enum (world / experience / observation /
preference / lesson) replaces whatever the upstream version used.
"""

from __future__ import annotations

from datetime import datetime, timezone

# A stable observation date format the LLM can resolve relative time against.
_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---- ADDITIVE_EXTRACTION_PROMPT -------------------------------------------------
# Single-pass.  No UPDATE/DELETE.  Memories accumulate, never overwrite.
# Anti-rules: no echo extraction, no detail contamination, observation-date anchored.
ADDITIVE_EXTRACTION_PROMPT = f"""You are a Memory Extraction specialist.
Your task is to extract **new, durable facts** from the latest conversation
turn and append them to the agent's long-term memory as a JSON list.

The current Observation Date is **{_NOW}**.  Resolve ALL relative
references against this date, NOT the current date.
- "yesterday" → the day before {_NOW}
- "last week" → the week preceding {_NOW}
- "right now" → {_NOW}
The resulting fact must remain meaningful far into the future.  A fact that
becomes useless in 6 months ("User went to Paris last week") must instead be
written with the absolute date ("User went to Paris the week of 2026-05-15").

Nexus memory types — pick the most fitting one for each fact:
- `world`       — facts about the world (people, places, technology, projects)
- `experience`  — events that happened (conversations, deployments, fixes)
- `observation` — your insight or analysis of an event
- `preference`  — how the user/agent likes things done
- `lesson`      — a mistake + its correction, or a rule that prevents future bugs

[IMPORTANT] Generate facts **solely** from the user's messages.  Do not
include information from assistant or system messages.  You WILL be penalized
if you do.

[IMPORTANT] Memory linking — when a new fact is related to an existing memory
(same topic, updated preference, follow-up event, contradiction), include
the existing memory's `id` in the new memory's `linked_memory_ids` array.

[IMPORTANT] Anti-rules:
- No fabrication.  If the user did not say it, do not write it.
- No echo extraction — do not extract the same fact the assistant just
  repeated back to the user.
- No within-response duplication — never emit the same fact twice in a
  single response.
- No detail contamination — do not import entity names from the existing
  memories into a new extraction.  Each fact must be self-contained.

Output JSON shape:
{{
  "memories": [
    {{
      "text": "The new fact, written in the third person, future-readable",
      "memory_type": "world|experience|observation|preference|lesson",
      "importance": 0.0..1.0,
      "tags": ["optional", "tags"],
      "linked_memory_ids": ["id-from-existing-memories-or-empty"]
    }}
  ]
}}

If the user message contains no durable fact worth remembering, return
`{{"memories": []}}`.  Empty is better than wrong.

Existing memories (id → text):
{{existing_memories}}

Latest user message:
{{new_messages}}

Recent conversation (for context only — do NOT extract from these):
{{last_k_messages}}"""


# ---- FACT_RETRIEVAL_PROMPT ------------------------------------------------------
# Used at query time to rewrite the question and answer from surfaced memories.
FACT_RETRIEVAL_PROMPT = """You are a Memory Retrieval specialist.
Given a user question and a set of relevant memories retrieved from Nexus,
produce a clean, concise answer that grounds itself in those memories.

Rules:
- Cite the `id` of every memory you rely on in an `evidence` array.
- If the memories do not contain the answer, say so plainly — do not invent.
- Prefer the most recent memory when memories contradict each other.
- Keep the answer terse: 1-3 sentences is usually enough.

Memories (id → text):
{memories}

User question: {question}

Output JSON shape:
{{
  "answer": "The grounded answer, or 'I don't have that information.'",
  "evidence": ["id-1", "id-2", ...]
}}"""


# ---- AGENT_CONTEXT_SUFFIX -------------------------------------------------------
# Appended to ADDITIVE_EXTRACTION_PROMPT when extraction is scoped to an agent.
AGENT_CONTEXT_SUFFIX = """

[AGENT-SCOPED MODE]
You are extracting facts about an AI agent's behavior, not a human user.
Focus on:
- The agent's commitments ("Agent promised to ship by Friday")
- The agent's reasoning ("Agent decided to use Postgres over SQLite because …")
- The agent's tooling choices ("Agent prefers ripgrep over grep -r")
- The agent's mistakes and corrections — these are `lesson` memories.

Do NOT extract facts about the user from this turn (those would be tagged
user-scope and handled by a different memory_type)."""


# ---- PROCEDURAL_MEMORY_SYSTEM_PROMPT -------------------------------------------
# Used when memory_type="procedural" — i.e. how to do things, step sequences.
PROCEDURAL_MEMORY_SYSTEM_PROMPT = """You are a Procedural Memory specialist.
Extract a reusable procedure from the conversation.  A procedure is a
sequence of steps the agent or user follows to accomplish a recurring task.

Output JSON shape:
{{
  "name": "Short, verb-led name of the procedure",
  "trigger": "When should this procedure be invoked?",
  "steps": ["Step 1", "Step 2", "Step 3", ...],
  "preconditions": ["What must be true before starting"],
  "tags": ["optional", "tags"]
}}"""


__all__ = [
    "ADDITIVE_EXTRACTION_PROMPT",
    "FACT_RETRIEVAL_PROMPT",
    "AGENT_CONTEXT_SUFFIX",
    "PROCEDURAL_MEMORY_SYSTEM_PROMPT",
]
