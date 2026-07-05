# Nexus Living Mind — "Conscious Mind" Upgrade — Handoff

**Start Claude Code in this directory (on kubuntux, via SSH):**

```
/media/kubuntux/DEVELOPMENT1/synapse-memory
```

That is the Nexus server source. It runs as Docker containers (`nexus-nexus-api-1`, `nexus-nexus-worker-1`, `nexus-postgres-1`, `nexus-redis-1`, `nexus-llama-server-1`) also on kubuntux. All work so far has been done directly on kubuntux over `ssh kubuntux`, editing files under that path and running `docker compose up -d --force-recreate nexus-api nexus-worker` to pick up changes.

## What this work is

Continuing an in-progress task (originally started by "codex," continued by Claude) to make the Nexus "Living Mind" behave like a continuously-running conscious entity instead of a pure request/response reasoner. Two parts:

1. **Done and verified live:** switched the mind's primary LLM to OpenCode Zen (`deepseek-v4-flash-free`, via `OPENAI_BASE_URL=https://opencode.ai/zen/v1`), with local Ollama (`qwen2.5-3b-instruct`) as fallback. Confirmed via a live `/v1/mind/think` call and container logs showing `primary LLM: deepseek-v4-flash-free`.
2. **In progress:** background self-reflection loop + proactive push, so the mind organizes memory, reflects on new information, and surfaces notable opinions without being asked — not just when a `/think` request comes in.

## User's design decisions (already made, don't re-ask)

- **One global mind**, not per-agent — a single mind (`mind_id="nexus"`) reflects over all shared memory.
- **Threshold-gated proactive push** — only push to agents when a reflection crosses a novelty/confidence bar (stance flips, or strength crosses 0.75); otherwise just log it quietly.

## What already existed before this session (don't rebuild)

- Background memory organization/dedup/decompose (`app/memory/organize.py`, `consolidate.py`, `decompose.py`, `merge.py`) — already finished and wired by codex, runs on the existing hourly `_mind_periodic_learning_loop` in `app/main.py`.
- `ReasoningEngine.reflect()`, `LivingMind.reflect()`, `OpinionSystem`, `ProactiveManager`, `publish_push_event()` (Redis stream `nexus:push`), and the SSE `/stream` endpoint — all real, all reused by the new loop rather than duplicated.

## Files changed this session (all on kubuntux, each has a timestamped `.bak-*` sibling before edits)

- `app/mind/active.py` — fixed a bug: `MemoryRouter.save()` used to call `mind.think(question=content)`, treating a stored fact as a question (misfires intent classification). Now calls `mind.opinions.form_or_update()` directly against the extracted topic.
- `migrations/011_mind_reflection.sql` — new `mind_reflection_log` table (mind_id, topic, stance, strength, summary, triggered_push, created_at).
- `app/config.py` — new settings: `mind_reflection_enabled`, `mind_reflection_mind_id` (default `"nexus"`), `mind_reflection_interval_seconds` (1800s), `mind_reflection_lookback_memories`, `mind_reflection_max_topics_per_cycle`, `mind_reflection_push_stance_delta` (0.3), `mind_reflection_push_min_strength` (0.75). Also explicitly declared `mind_learning_interval_seconds` (was previously only read via `getattr` with no declared field).
- `docker-compose.yml` — added `OPENAI_BASE_URL` and the new reflection env vars to both `nexus-api` and `nexus-worker` service blocks (they weren't passed through before — `.env` alone doesn't reach a container without an explicit `environment:` entry in compose).
- `app/main.py` — added `_mind_reflection_loop()`: keeps the global mind resident via `_get_mind()`, pulls memories since the last cycle by direct SQL, derives topics via `mind._extract_topic()`, calls `mind.reflect(topic)` + `mind.opinions.form_or_update()` per topic, writes every cycle to `mind_reflection_log`, and pushes via `ProactiveManager.surface()` + `publish_push_event(event="mind_reflection")` only when the threshold is crossed. Wired into `lifespan()` startup (`asyncio.create_task`) and shutdown (`.cancel()`), also loads migration 011 the same way migration 006 is loaded (inline SQL-file read, not auto-discovered).

## Known issue just fixed, needs re-verification

A shell heredoc mangled a string literal while writing the reflection loop docstring and a config default (`mind_reflection_mind_id: str = nexus` — missing quotes around `nexus`), which crashed `nexus-nexus-worker-1` on boot with `NameError: name 'nexus' is not defined`. Fixed via `sed` and confirmed `python3 -m py_compile` passes on all four touched files. **Containers were just restarted after the fix — this had not yet been re-verified as fully healthy when this document was written.**

## Next steps when resuming

1. Check container health: `ssh kubuntux "docker ps --format '{{.Names}}\t{{.Status}}'"` — all `nexus-*` should show `healthy`, not `Restarting`.
2. Check startup logs for the reflection loop: `ssh kubuntux "docker logs nexus-nexus-api-1 --since 2m 2>&1 | grep -i 'reflect\|migration\|error\|traceback'"`.
3. Confirm migration 011 applied: query `SELECT * FROM mind_reflection_log LIMIT 1;` (table should exist even if empty) via `docker exec` psql.
4. Wait for or force a reflection cycle (default interval 1800s; can temporarily lower `MIND_REFLECTION_INTERVAL_SECONDS` for testing) and confirm a row appears in `mind_reflection_log`.
5. Manufacture a stance-flip (save a memory that strongly contradicts an existing opinion) and confirm a push fires — check `triggered_push = true` in the log row, and watch `/stream` or the `nexus:push` Redis stream for the `mind_reflection` event.
6. Nothing has been committed to git yet — all changes are uncommitted working-tree edits on kubuntux, same as the codex work that was already in progress before this session.
