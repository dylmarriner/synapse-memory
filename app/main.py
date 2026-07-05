"""
Nexus — Unified Agent Memory Server
Tailscale: http://100.93.75.87:7777
MCP: http://100.93.75.87:7777/mcp
Dashboard: http://100.93.75.87:7777/
"""

import asyncio
import os
from typing import Optional, Dict, Any
import hashlib
import hmac
import logging
import socket
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy import text

from app.config import settings


def _make_dashboard_token() -> str:
    """Generate a short-lived HMAC token scoped to dashboard read-only access."""
    ts = str(int(time.time()) // 3600)
    return hmac.new(
        settings.nexus_secret.encode(), f"dashboard:{ts}".encode(), hashlib.sha256
    ).hexdigest()[:48]


def _verify_dashboard_token(token: str) -> bool:
    """Verify a dashboard-scoped token (valid for current and previous hour)."""
    if not settings.nexus_secret:
        return False
    for offset in (0, -1):
        ts = str(int(time.time()) // 3600 + offset)
        expected = hmac.new(
            settings.nexus_secret.encode(), f"dashboard:{ts}".encode(), hashlib.sha256
        ).hexdigest()[:48]
        if hmac.compare_digest(token, expected):
            return True
    return False
from app.db import engine, SessionLocal, is_sqlite
from app.models.schema import Base
from app.routers.memory import router as memory_router
from app.routers.agents import router as agents_router
from app.routers.search import router as search_router
from app.routers.admin import router as admin_router
from app.routers.browse import router as browse_router
from app.routers.stream import router as stream_router
from app.routers.rtk import router as rtk_router
from app.routers.sessions import router as sessions_router
from app.mcp import mcp_router
from app.routers.sys_bridge import router as sys_bridge_router
from app.routers.synapse import router as synapse_router
from app.routers.compat import router as compat_router
from app.routers.graph import router as graph_router
from app.routers.hooks import router as hooks_router
from app.routers.adopted import router as adopted_router
from app.routers.mind import router as mind_router
from app.routers.layers import router as layers_router
from app.routers.code import router as code_router
from app.routers.federation import router as federation_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("nexus")


def _setup_otel(app: "FastAPI") -> None:
    """Initialize OpenTelemetry tracing if OTEL_ENABLED=true."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        log.info("OpenTelemetry tracing enabled → %s", settings.otel_endpoint)
    except ImportError:
        log.warning("OTEL_ENABLED=true but opentelemetry packages not installed; skipping")


async def _run_migrations():
    """Apply schema upgrades safely using IF NOT EXISTS / ADD COLUMN IF NOT EXISTS."""
    async with engine.begin() as conn:
        # Base tables via ORM
        await conn.run_sync(Base.metadata.create_all)

        # The remaining migrations use PostgreSQL-only syntax and extensions.
        # SQLite embedded databases are fully created from the ORM schema.
        if is_sqlite():
            return

        async def _safe_exec(sql, params=None, *, level="debug", label="migration step"):
            """Run one idempotent migration statement inside its own SAVEPOINT.

            asyncpg aborts the *entire* transaction on any statement error, so
            without per-statement isolation one failure silently skips every
            following statement (IF NOT EXISTS or not).  Wrapping each in a
            nested transaction means a failure rolls back only that savepoint
            and the migration continues.
            """
            try:
                async with conn.begin_nested():
                    await conn.execute(sql if not isinstance(sql, str) else text(sql), params or {})
            except Exception as e:
                getattr(log, level, log.debug)("%s skipped: %s", label, e)

        # Add new columns if upgrading from an older schema
        for col_sql in [
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS confirmed_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS contradicted_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES memories(id) ON DELETE SET NULL",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS session_count INT NOT NULL DEFAULT 0",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS model VARCHAR(100)",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS confidence FLOAT NOT NULL DEFAULT 1.0",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS extraction_model VARCHAR(100)",
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS extraction_version VARCHAR(50)",
            "ALTER TABLE relations ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE relations ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ",
        ]:
            await _safe_exec(col_sql)

        # Summaries table (in case ORM didn't create it yet)
        await _safe_exec("""
            CREATE TABLE IF NOT EXISTS summaries (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                content     TEXT NOT NULL,
                memory_count INT NOT NULL DEFAULT 0,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """, label="summaries table")
        await _safe_exec("CREATE INDEX IF NOT EXISTS idx_summaries_agent ON summaries(agent_id)")
        await _safe_exec("CREATE INDEX IF NOT EXISTS idx_summaries_agent_time ON summaries(agent_id, created_at DESC)")

        # Backfill missing column defaults for tables created before defaults were added
        for alter_default_sql in [
            "ALTER TABLE summaries ALTER COLUMN id SET DEFAULT gen_random_uuid()",
        ]:
            await _safe_exec(alter_default_sql)

        for index_sql in [
            "CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw ON memories USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
            "CREATE INDEX IF NOT EXISTS idx_memories_type_priority ON memories(memory_type, importance DESC, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memories_tags_gin ON memories USING gin ((metadata->'tags'))",
            "CREATE INDEX IF NOT EXISTS idx_agents_last_active ON agents (last_active DESC)",
            "CREATE INDEX IF NOT EXISTS idx_agents_model ON agents (model)",
            # FTS index for lexical search (sequential scan fallback without this)
            "CREATE INDEX IF NOT EXISTS idx_memories_fts ON memories USING gin(to_tsvector('english', content))",
            # Composite indexes for per-agent temporal + importance queries
            "CREATE INDEX IF NOT EXISTS idx_memories_agent_time ON memories(agent_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memories_agent_importance ON memories(agent_id, importance DESC)",
            # Superseded chain lookup
            "CREATE INDEX IF NOT EXISTS idx_memories_superseded_by ON memories(superseded_by) WHERE superseded_by IS NOT NULL",
            # Active memory filter (hot path for all four search engines)
            "CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(id) WHERE superseded_by IS NULL",
            # Bi-temporal relation index
            "CREATE INDEX IF NOT EXISTS idx_relations_valid_from ON relations(valid_from)",
        ]:
            await _safe_exec(index_sql, level="warning", label="Optional index")

        # Synapse-compat tables: projects, file_index, events
        for compat_sql in [
            """
            CREATE TABLE IF NOT EXISTS projects (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                key         TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL,
                root        TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS file_index (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_key TEXT NOT NULL,
                path        TEXT NOT NULL,
                sha256      TEXT NOT NULL,
                size        INT NOT NULL DEFAULT 0,
                language    TEXT,
                summary     TEXT,
                symbols     JSONB NOT NULL DEFAULT '[]',
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (project_key, path)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_key TEXT NOT NULL,
                actor       TEXT NOT NULL,
                action      TEXT NOT NULL,
                detail      TEXT NOT NULL DEFAULT '',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ]:
            await _safe_exec(compat_sql.strip(), level="warning", label="Synapse table create")

        for compat_idx in [
            "CREATE INDEX IF NOT EXISTS idx_projects_key ON projects(key)",
            "CREATE INDEX IF NOT EXISTS idx_file_index_project ON file_index(project_key)",
            "CREATE INDEX IF NOT EXISTS idx_file_index_lang ON file_index(language)",
            "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_key)",
            "CREATE INDEX IF NOT EXISTS idx_events_time ON events(project_key, created_at DESC)",
        ]:
            await _safe_exec(compat_idx, level="warning", label="Synapse index")

        # Raw session archive + memory provenance tables.
        for session_sql in [
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_id    UUID REFERENCES agents(id) ON DELETE SET NULL,
                agent_name  TEXT NOT NULL,
                project_key TEXT,
                title       TEXT,
                started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ended_at    TIMESTAMPTZ,
                metadata    JSONB NOT NULL DEFAULT '{}'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id     UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role           TEXT NOT NULL,
                content        TEXT NOT NULL,
                token_estimate INT NOT NULL DEFAULT 0,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata       JSONB NOT NULL DEFAULT '{}'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS memory_sources (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                memory_id   UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                source_kind TEXT NOT NULL,
                source_id   UUID NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata    JSONB NOT NULL DEFAULT '{}',
                UNIQUE(memory_id, source_kind, source_id)
            )
            """,
        ]:
            await _safe_exec(session_sql.strip(), level="warning", label="Session table create")

        for session_idx in [
            "CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_key, started_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_id, created_at ASC)",
            "CREATE INDEX IF NOT EXISTS idx_memory_sources_memory ON memory_sources(memory_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_sources_source ON memory_sources(source_kind, source_id)",
        ]:
            await _safe_exec(session_idx, level="warning", label="Session index")

        # Adopted-pattern tables (migration 005).  Each block is wrapped
        # in its own try/except so a partial migration never blocks startup.
        try:
            _migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            with open(_migration_dir / "005_adopted.sql") as _f:
                adopted_sql = _f.read()
            for stmt in [s.strip() for s in adopted_sql.split(";") if s.strip()]:
                # Skip pure comments / blanks.
                if not stmt or all(line.strip().startswith("--") for line in stmt.splitlines() if line.strip()):
                    continue
                await _safe_exec(stmt, label="Adopted SQL step")
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("Adopted migration block failed: %s", e)

        # Living Mind tables (migration 006).  Same try/except pattern —
        # never block startup on a partial migration.
        try:
            _migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            with open(_migration_dir / "006_living_mind.sql") as _f:
                mind_sql = _f.read()
            for stmt in [s.strip() for s in mind_sql.split(";") if s.strip()]:
                if not stmt or all(line.strip().startswith("--") for line in stmt.splitlines() if line.strip()):
                    continue
                await _safe_exec(stmt, label="Mind SQL step")
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("Living Mind migration block failed: %s", e)

        # Mind reflection log (migration 011).  Same try/except pattern.
        try:
            _migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            with open(_migration_dir / "011_mind_reflection.sql") as _f:
                reflection_sql = _f.read()
            for stmt in [s.strip() for s in reflection_sql.split(";") if s.strip()]:
                if not stmt or all(line.strip().startswith("--") for line in stmt.splitlines() if line.strip()):
                    continue
                await _safe_exec(stmt, label="Mind reflection SQL step")
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("Mind reflection migration block failed: %s", e)


        # Backfill basic device metadata so the dashboard can place legacy agents.
        await _safe_exec("""
            UPDATE agents
            SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb)
            WHERE NOT (metadata ? 'device') AND name != 'global'
        """, {"patch": '{"device": "' + socket.gethostname() + '", "source": "nexus-api"}'},
            level="warning", label="Agent device metadata backfill")


async def _ensure_global_agent():
    """Ensure the 'global' shared pool agent exists."""
    async with SessionLocal() as db:
        try:
            await db.execute(text("""
                INSERT INTO agents (name, metadata)
                VALUES ('global', '{"system": true, "description": "Shared global memory pool"}')
                ON CONFLICT (name) DO NOTHING
            """))
            await db.commit()
        except Exception as e:
            log.warning("Global agent ensure failed: %s", e)


async def _learning_loop(redis_client: aioredis.Redis, interval: int):
    while True:
        await asyncio.sleep(interval)
        try:
            await redis_client.rpush("nexus:consolidate", "1")
        except Exception as e:
            log.warning("Learning loop push failed: %s", e)


async def _mind_periodic_learning_loop(interval_seconds: int = 3600):
    """Periodic mind learning: prune old patterns, then persist each mind.

    Runs every `interval_seconds` (default: 1 hour).  Per-mind work:
    prune patterns older than 90 days, then flush the mind's identity,
    opinions, and relationships to the database so the evolved state is
    durable across restarts even when no conversation explicitly ends.
    """
    # Lazily import the mind module — it's a separate subsystem.
    from app.mind import persist as _persist
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Get all in-process minds from the router.
            from app.routers import mind as mind_router
            minds = list(mind_router._MINDS.values())
            for mind in minds:
                try:
                    pruned = mind.identity.prune_old_patterns(
                        max_age_days=90, max_patterns=200
                    )
                    if pruned:
                        log.info(
                            "mind '%s' pruned %d old patterns",
                            mind.mind_id, pruned,
                        )
                except Exception as e:
                    log.debug("mind '%s' pruning failed: %s", mind.mind_id, e)
                # Flush evolved state to the database (best-effort).
                try:
                    async with SessionLocal() as db:
                        await _persist.save_mind(mind, db)
                except Exception as e:
                    log.debug("mind '%s' periodic save failed: %s", mind.mind_id, e)
            try:
                if settings.llm_memory_organizer_enabled:
                    from app.memory.organize import organize_memories
                    async with SessionLocal() as db:
                        organizer_stats = await organize_memories(db)
                    if organizer_stats.get("organizer_clusters"):
                        log.info("mind organizer cycle: %s", organizer_stats)
            except Exception as e:
                log.debug("mind periodic organizer failed: %s", e)
        except Exception as e:
            log.warning("Mind periodic learning failed: %s", e)


async def _mind_reflection_loop(interval_seconds: int = 1800):
    """Background self-reflection for one global mind.

    Unlike _mind_periodic_learning_loop (decay + persist + organize),
    this loop makes the mind actually think about what it has recently
    learned without being asked: it pulls recently-saved memories, derives
    a handful of topics from them, reflects on each via the reasoning
    engine, and forms/updates opinions from the result -- the same
    opinion-forming step think() does on a normal question, just
    self-triggered instead of request-triggered.

    When a reflection produces a stance flip or a strong new opinion
    (crossing mind_reflection_push_stance_delta or
    mind_reflection_push_min_strength), it is surfaced proactively via
    the existing push daemon so connected agents see it unprompted.
    Anything below that bar is still recorded (opinion updated, logged
    to mind_reflection_log) but silently -- no push spam every cycle.
    """
    from app.mind import persist as _persist
    from app.routers.mind import _get_mind

    mind_id = settings.mind_reflection_mind_id
    last_reflected_at: Optional[str] = None

    while True:
        await asyncio.sleep(interval_seconds)
        if not settings.mind_reflection_enabled:
            continue
        try:
            mind = _get_mind(mind_id)

            # Pull recently-saved memories since the last reflection cycle.
            async with SessionLocal() as db:
                rows = (await db.execute(text("""
                    SELECT id::text AS id, content, memory_type, importance,
                           agent_id::text AS agent_id, created_at
                    FROM memories
                    WHERE superseded_by IS NULL
                      AND (CAST(:since AS timestamptz) IS NULL OR created_at > CAST(:since AS timestamptz))
                    ORDER BY created_at DESC
                    LIMIT :limit
                """), {"since": last_reflected_at, "limit": settings.mind_reflection_lookback_memories})).mappings().all()
            memories = [dict(r) for r in rows]
            if not memories:
                continue
            last_reflected_at = memories[0]["created_at"].isoformat()

            # Derive a small set of topics from the new memories.
            topics: List[str] = []
            for m in memories:
                topic = mind._extract_topic(m.get("content", ""))
                if topic and topic not in topics:
                    topics.append(topic)
                if len(topics) >= settings.mind_reflection_max_topics_per_cycle:
                    break

            for topic in topics:
                try:
                    prior = mind.opinions.get(topic)
                    prior_strength = prior.strength if prior else None

                    reflection = await mind.reflect(topic=topic)
                    topic_memories = [
                        m for m in memories
                        if topic in m.get("content", "").lower()
                    ] or memories
                    opinion = await mind.opinions.form_or_update(
                        topic=topic,
                        evidence=topic_memories,
                        current_stance_hint=reflection.reasoning_trace.stance_hint
                        if reflection.reasoning_trace else None,
                    )

                    triggered_push = False
                    if opinion is not None:
                        strength_delta = (
                            abs(opinion.strength - prior_strength)
                            if prior_strength is not None else opinion.strength
                        )
                        crosses_bar = (
                            strength_delta >= settings.mind_reflection_push_stance_delta
                            or opinion.strength >= settings.mind_reflection_push_min_strength
                        )
                        if crosses_bar:
                            triggered_push = True
                            try:
                                from app.mind.active import ProactiveManager
                                proactive = ProactiveManager(mind)
                                await proactive.surface(agent_id=None, question=topic)
                            except Exception as e:
                                log.debug("reflection proactive surface failed: %s", e)
                            try:
                                redis_client = app.state.redis
                                from app.push.daemon import publish_push_event
                                await publish_push_event(redis_client, agent_id="*", event="mind_reflection")
                            except Exception as e:
                                log.debug("reflection push publish failed: %s", e)

                    try:
                        async with SessionLocal() as db:
                            await _persist.ensure_mind_row(mind.mind_id, db)
                            await db.execute(text("""
                                INSERT INTO mind_reflection_log
                                    (mind_id, topic, stance, strength, summary, triggered_push)
                                SELECT id, :topic, :stance, :strength, :summary, :triggered_push
                                FROM minds WHERE name = :mind_name
                            """), {
                                "topic": topic,
                                "stance": opinion.stance.value if opinion else None,
                                "strength": opinion.strength if opinion else None,
                                "summary": (reflection.answer or "")[:2000],
                                "triggered_push": triggered_push,
                                "mind_name": mind.mind_id,
                            })
                            await db.commit()
                    except Exception as e:
                        log.debug("reflection log write failed: %s", e)

                    log.info(
                        "mind '%s' reflected on '%s' (push=%s)",
                        mind.mind_id, topic, triggered_push,
                    )
                except Exception as e:
                    log.debug("reflection on topic '%s' failed: %s", topic, e)

            try:
                async with SessionLocal() as db:
                    await _persist.save_mind(mind, db)
            except Exception as e:
                log.debug("mind '%s' reflection-cycle save failed: %s", mind.mind_id, e)
        except Exception as e:
            log.warning("Mind reflection loop failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Nexus starting — port %d", settings.nexus_port)

    if settings.nexus_disable_auth:
        if settings.environment != "development":
            raise RuntimeError(
                "NEXUS_DISABLE_AUTH is set but ENVIRONMENT is not 'development' — "
                "refusing to start with auth disabled outside development."
            )
        log.critical(
            "AUTH IS DISABLED (NEXUS_DISABLE_AUTH=true, ENVIRONMENT=development) — "
            "every request bypasses authentication. Do not expose this instance."
        )

    await _run_migrations()
    await _ensure_global_agent()
    # Auto-register the nexus-self repo on first boot so the code
    # index is queryable immediately.  No-op if the path is missing.
    try:
        if os.path.isdir("/app"):
            from app.code.indexer import get_or_create_repo
            from app.db import SessionLocal
            async with SessionLocal() as db:
                await get_or_create_repo(db, "nexus-self", "/app", "system")
    except Exception as e:
        log.debug("auto-register nexus-self skipped: %s", e)

    from app.redis_util import make_redis
    redis_client = make_redis(decode_responses=True)
    app.state.redis = redis_client
    app.state.settings = settings

    task = asyncio.create_task(
        _learning_loop(redis_client, settings.learning_interval)
    )

    # Periodic Living Mind learning — prune old patterns every hour.
    mind_learning_interval = int(getattr(settings, "mind_learning_interval_seconds", 3600))
    mind_learning_task = asyncio.create_task(
        _mind_periodic_learning_loop(mind_learning_interval)
    )
    log.info("Mind periodic learning started (every %ds)", mind_learning_interval)

    # Background self-reflection loop — one global mind thinks about
    # recent memories unprompted and surfaces notable opinions proactively.
    reflection_task = asyncio.create_task(
        _mind_reflection_loop(settings.mind_reflection_interval_seconds)
    )
    log.info(
        "Mind reflection loop started (every %ds, enabled=%s)",
        settings.mind_reflection_interval_seconds, settings.mind_reflection_enabled,
    )

    # Start the scheduler for daily consolidation reports
    from app.scheduler import scheduler_loop
    scheduler_task = asyncio.create_task(scheduler_loop())
    log.info("Scheduler started for daily consolidation reports")

    # Start active memory push daemon
    from app.push.daemon import PushDaemon
    push_daemon = PushDaemon(redis_client)
    push_task = asyncio.create_task(push_daemon.start())
    log.info("Active memory push daemon started")

    # Embedded mode: run the extraction worker in-process so no separate
    # worker container is needed (it shares the in-process fakeredis queue).
    embedded_worker_task = None
    if settings.embedded_mode:
        from app.memory.extract import run_worker
        embedded_worker_task = asyncio.create_task(run_worker())
        log.info("Embedded mode: extraction worker running in-process")

    # Start federation pull loop (no-op unless FEDERATION_ENABLED=true).
    from app.federation import federation_loop
    federation_task = asyncio.create_task(federation_loop())
    if settings.federation_enabled:
        log.info("Federation enabled — node=%s", settings.federation_node_id or "<hostname>")

    # Note: the code-context inotify watcher lives in the host (see
    # scripts/nexus-code-watch.sh) because the container's /app is a
    # read-only bind mount. We don't start the watcher inside the
    # container because inotify wouldn't see host-side writes through a
    # :ro bind.

    log.info("Nexus ready — REST: /v1  MCP: /mcp  Dashboard: /")
    yield

    task.cancel()
    mind_learning_task.cancel()
    reflection_task.cancel()
    scheduler_task.cancel()
    push_daemon.stop()
    push_task.cancel()
    federation_task.cancel()
    if embedded_worker_task:
        embedded_worker_task.cancel()
    await redis_client.aclose()
    await engine.dispose()
    log.info("Nexus stopped")


app = FastAPI(
    title="Nexus",
    description="Unified agent memory — semantic · lexical · graph · temporal recall.",
    version="1.0.0",
    lifespan=lifespan,
)

if settings.otel_enabled:
    _setup_otel(app)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def _verify_key(request: Request):
    if settings.nexus_disable_auth and settings.environment == "development":
        log.critical("AUTH BYPASSED for %s %s (NEXUS_DISABLE_AUTH=true)", request.method, request.url.path)
        return
    secret = settings.nexus_secret
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="NEXUS_SECRET not configured")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = auth.removeprefix("Bearer ").strip()
    if token == secret:
        return
    # Separate dashboard password — lets the web UI authenticate without the
    # agent-facing secret.  Only honoured when configured.
    dash_pw = settings.dashboard_password
    if dash_pw and token == dash_pw:
        return
    if _verify_dashboard_token(token):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


app.include_router(memory_router,  prefix="/v1/memory",  tags=["memory"],  dependencies=[Depends(_verify_key)])
app.include_router(agents_router,  prefix="/v1/agents",  tags=["agents"],  dependencies=[Depends(_verify_key)])
app.include_router(search_router,  prefix="/v1/search",  tags=["search"],  dependencies=[Depends(_verify_key)])
app.include_router(admin_router,   prefix="/v1",         tags=["admin"],   dependencies=[Depends(_verify_key)])
app.include_router(browse_router,  prefix="/v1/browse",  tags=["browse"],  dependencies=[Depends(_verify_key)])
app.include_router(stream_router,  prefix="/v1",         tags=["stream"])  # auth handled internally (EventSource can't set headers)
app.include_router(rtk_router,     prefix="/v1/rtk",     tags=["rtk"],     dependencies=[Depends(_verify_key)])
app.include_router(sessions_router, prefix="/v1/sessions", tags=["sessions"], dependencies=[Depends(_verify_key)])
app.include_router(mcp_router,        prefix="/mcp",           tags=["mcp"],        dependencies=[Depends(_verify_key)])
app.include_router(sys_bridge_router,  prefix="/v1/sys",  tags=["sys"],  dependencies=[Depends(_verify_key)])
app.include_router(synapse_router, prefix="/v1/synapse", tags=["synapse"], dependencies=[Depends(_verify_key)])
app.include_router(compat_router, prefix="/v1",        tags=["compat"],  dependencies=[Depends(_verify_key)])
app.include_router(graph_router,  prefix="/v1",        tags=["graph"],   dependencies=[Depends(_verify_key)])
app.include_router(hooks_router,  prefix="/v1/hooks",  tags=["hooks"],   dependencies=[Depends(_verify_key)])
app.include_router(adopted_router,                     tags=["adopted"], dependencies=[Depends(_verify_key)])
app.include_router(mind_router,                        tags=["mind"],    dependencies=[Depends(_verify_key)])
app.include_router(layers_router,                      tags=["layers"], dependencies=[Depends(_verify_key)])
app.include_router(code_router,                        tags=["code"],   dependencies=[Depends(_verify_key)])
# Federation routes authenticate by HMAC signature, not the agent Bearer secret.
app.include_router(federation_router, prefix="/v1/federation", tags=["federation"])


# Serve the built React/Vite dashboard at /app (when present).  The bundle is
# the client shell only — it's unauthenticated, but every /v1 data call it
# makes is gated by _verify_key, and the app prompts for the dashboard
# password.  Built with base='/app/' so asset URLs resolve here.
try:
    from fastapi.staticfiles import StaticFiles
    _dash_dist = Path(__file__).resolve().parents[1] / "dashboard" / "dist"
    if _dash_dist.is_dir():
        app.mount("/app", StaticFiles(directory=str(_dash_dist), html=True), name="dashboard-app")
        log.info("Serving React dashboard from %s at /app", _dash_dist)
    else:
        log.info("React dashboard dist not found at %s — /app not mounted", _dash_dist)
except Exception as e:
    log.warning("Dashboard static mount skipped: %s", e)


@app.get("/.well-known/nexus/openapi.json", include_in_schema=False)
async def nexus_openapi_spec():
    return FileResponse("integrations/openapi/nexus-memory.openapi.json", media_type="application/json")


@app.get("/.well-known/nexus/plugin-manifest.json", include_in_schema=False)
async def nexus_plugin_manifest():
    return FileResponse("integrations/plugins/universal-agent-plugin.manifest.json", media_type="application/json")


@app.get("/v1/mind/dashboard/panel", include_in_schema=False)
async def mind_dashboard_panel(mind_id: str = "default"):
    """A small HTML panel of one mind's state for the main dashboard.

    Returns a self-contained HTML fragment that the operator's
    dashboard can fetch and inject.  Includes identity summary,
    learned patterns, active opinions, and recent conversations.
    """
    from app.routers.mind import dashboard as _mind_dashboard
    data = await _mind_dashboard(mind_id=mind_id)
    html_parts = [
        "<section class='mind-dashboard'>",
        f"<h2>Living Mind: {data['mind_id']}</h2>",
        f"<p class='description'>{data['self_description']}</p>",
        "<div class='stats'>",
        f"  <span>patterns: {data['stats']['patterns_learned']}</span>",
        f"  <span>capabilities: {data['stats']['capabilities']}</span>",
        f"  <span>opinions: {data['stats']['opinions_held']}</span>",
        f"  <span>relationships: {data['stats']['relationships']}</span>",
        f"  <span>conversations: {data['stats']['active_conversations']}</span>",
        "</div>",
    ]
    if data.get("opinions"):
        html_parts.append("<h3>Active opinions</h3><ul>")
        for topic, op in data["opinions"].items():
            stance = op.get("stance", "?")
            strength = op.get("strength", 0)
            html_parts.append(
                f"<li><b>{topic}</b>: {stance} "
                f"(strength {strength:.2f}, "
                f"{op.get('evidence_count', 0)} pieces of evidence)</li>"
            )
        html_parts.append("</ul>")
    if data["identity"].get("learned_patterns"):
        html_parts.append("<h3>Recent patterns</h3><ul>")
        for p in data["identity"]["learned_patterns"][-5:]:
            html_parts.append(f"<li>{p['description']}</li>")
        html_parts.append("</ul>")
    html_parts.append("</section>")
    return HTMLResponse(content="\n".join(html_parts))


@app.get("/health")
async def health(request: Request):
    from app.routers.admin import health as _h
    async with SessionLocal() as db:
        return await _h(request, db)


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus Command Deck</title>
<style>
:root{
  --void:#02030a;--void2:#070916;--panel:rgba(9,16,34,.72);--panel2:rgba(4,10,24,.86);
  --line:rgba(102,252,241,.22);--line2:rgba(139,92,246,.24);--cyan:#66fcf1;--cyan2:#21d4fd;
  --violet:#b967ff;--magenta:#ff3cac;--amber:#ffd166;--green:#63ff9f;--red:#ff5470;
  --text:#d9fbff;--muted:#6e8c9b;--dim:#395461;--glow:0 0 28px rgba(102,252,241,.22);
}
*{box-sizing:border-box} html,body{height:100%} body{margin:0;overflow:hidden;background:radial-gradient(circle at 18% 14%,rgba(33,212,253,.18),transparent 28%),radial-gradient(circle at 82% 8%,rgba(255,60,172,.13),transparent 30%),linear-gradient(135deg,#01020a 0%,#071024 52%,#02030a 100%);color:var(--text);font-family:"Rajdhani","Orbitron","Eurostile",ui-sans-serif,system-ui,sans-serif;letter-spacing:.01em}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(102,252,241,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(102,252,241,.03) 1px,transparent 1px);background-size:42px 42px;mask-image:radial-gradient(circle at center,#000 0%,transparent 80%);animation:gridDrift 24s linear infinite}
body:after{content:"";position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0,rgba(255,255,255,.025) 1px,transparent 1px,transparent 4px);mix-blend-mode:overlay;opacity:.25}
@keyframes gridDrift{from{transform:translateY(0)}to{transform:translateY(42px)}}
button,input,select,textarea{font:inherit}button{cursor:pointer}.app{height:100%;display:grid;grid-template-columns:280px 1fr;grid-template-rows:1fr 38px;padding:18px;gap:16px}.shell{position:relative;border:1px solid var(--line);background:linear-gradient(180deg,rgba(6,14,31,.9),rgba(2,5,15,.92));box-shadow:var(--glow),inset 0 0 50px rgba(102,252,241,.035);clip-path:polygon(0 18px,18px 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%)}
.rail{grid-row:1/3;padding:18px;display:flex;flex-direction:column;gap:16px}.brand{padding:18px 14px 22px;border-bottom:1px solid var(--line);position:relative}.brand .kicker{color:var(--cyan);font-size:.72rem;text-transform:uppercase;letter-spacing:.28em}.brand h1{margin:8px 0 0;font-size:2.4rem;line-height:.9;letter-spacing:.08em;text-shadow:0 0 18px rgba(102,252,241,.65)}.brand .sub{color:var(--muted);font-size:.82rem;margin-top:9px}.orb{position:absolute;right:14px;top:18px;width:54px;height:54px;border-radius:50%;border:1px solid var(--cyan);background:radial-gradient(circle,#66fcf1 0 3px,transparent 4px),conic-gradient(from 90deg,transparent,var(--cyan),transparent,var(--violet),transparent);box-shadow:0 0 24px rgba(102,252,241,.35);animation:spin 9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.nav{display:flex;flex-direction:column;gap:8px}.nav button{background:rgba(102,252,241,.035);color:var(--muted);border:1px solid transparent;padding:13px 14px;text-align:left;text-transform:uppercase;letter-spacing:.14em;font-size:.78rem;display:flex;align-items:center;gap:11px;transition:.2s;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%)}.nav button:hover{border-color:var(--line);color:var(--text);transform:translateX(4px)}.nav button.active{background:linear-gradient(90deg,rgba(102,252,241,.18),rgba(185,103,255,.05));border-color:rgba(102,252,241,.45);color:var(--cyan);box-shadow:inset 3px 0 0 var(--cyan),0 0 22px rgba(102,252,241,.12)}
.sidePanel{border:1px solid var(--line2);background:rgba(3,8,20,.48);padding:12px;min-height:0;display:flex;flex-direction:column}.sideTitle{font-size:.72rem;color:var(--violet);text-transform:uppercase;letter-spacing:.2em;margin:0 0 10px}.agentList{overflow:auto;display:flex;flex-direction:column;gap:6px}.agent-item{border:1px solid rgba(102,252,241,.11);background:rgba(255,255,255,.025);padding:9px 10px;color:var(--muted);display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center}.agent-item:hover,.agent-item.active{border-color:var(--cyan);color:var(--text);background:rgba(102,252,241,.08)}.agent-count{color:var(--cyan);font-variant-numeric:tabular-nums}.main{min-width:0;display:flex;flex-direction:column;padding:18px;gap:16px}.topbar{display:flex;align-items:center;gap:16px}.titleBlock{flex:1}.titleBlock .eyebrow{color:var(--cyan);letter-spacing:.22em;text-transform:uppercase;font-size:.72rem}.titleBlock h2{margin:4px 0 0;font-size:2rem;letter-spacing:.05em}.status{display:flex;gap:10px;align-items:center;border:1px solid var(--line);background:rgba(102,252,241,.06);padding:10px 12px;color:var(--cyan);text-transform:uppercase;font-size:.75rem;letter-spacing:.12em}.dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 18px var(--green);animation:pulse 1.6s ease-in-out infinite}@keyframes pulse{50%{opacity:.45;transform:scale(.75)}}
.tabs{display:none;min-height:0;flex:1}.tabs.active{display:grid}.overview{grid-template-rows:auto 1fr;gap:16px}.statGrid{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px}.stat{position:relative;overflow:hidden;border:1px solid var(--line);background:linear-gradient(135deg,rgba(102,252,241,.1),rgba(185,103,255,.035));padding:16px;min-height:116px}.stat:before{content:"";position:absolute;right:-30px;top:-30px;width:90px;height:90px;border:1px solid rgba(102,252,241,.25);transform:rotate(45deg)}.stat .lbl{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.2em}.stat .val{font-size:2.4rem;color:var(--text);margin-top:12px;text-shadow:0 0 18px rgba(102,252,241,.35);font-variant-numeric:tabular-nums}.stat .sig{position:absolute;bottom:12px;right:14px;color:var(--dim);font-size:.7rem}.overviewGrid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;min-height:0}.panel{border:1px solid rgba(102,252,241,.2);background:var(--panel);padding:16px;min-height:0;overflow:hidden;position:relative}.panel h3{margin:0 0 12px;color:var(--cyan);letter-spacing:.16em;text-transform:uppercase;font-size:.82rem}.type-pills{display:flex;flex-wrap:wrap;gap:10px}.pill{border:1px solid rgba(102,252,241,.22);background:rgba(102,252,241,.045);padding:9px 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-size:.75rem}.pill.active,.pill:hover{color:var(--cyan);border-color:var(--cyan);box-shadow:0 0 18px rgba(102,252,241,.13)}.scanner{height:100%;min-height:220px;background:radial-gradient(circle at center,rgba(102,252,241,.14),transparent 55%);position:relative;overflow:hidden}.scanner:before{content:"";position:absolute;inset:18%;border:1px solid rgba(102,252,241,.28);border-radius:50%;box-shadow:0 0 35px rgba(102,252,241,.12),inset 0 0 35px rgba(102,252,241,.08)}.scanner:after{content:"";position:absolute;inset:0;background:conic-gradient(from 0deg,transparent 0 70%,rgba(102,252,241,.35));animation:spin 6s linear infinite}.scannerText{position:absolute;inset:auto 18px 18px;color:var(--muted);font-size:.78rem;letter-spacing:.12em;text-transform:uppercase}.vault{grid-template-rows:auto 1fr auto;gap:12px}.tools{display:grid;grid-template-columns:1fr 170px 140px;gap:10px}.field{background:rgba(2,5,14,.72);border:1px solid rgba(102,252,241,.22);color:var(--text);padding:12px 14px;outline:none}.field:focus{border-color:var(--cyan);box-shadow:0 0 18px rgba(102,252,241,.12)}.memories{overflow:auto;display:grid;gap:10px;padding-right:6px}.mem-card{position:relative;border:1px solid rgba(102,252,241,.17);background:linear-gradient(135deg,rgba(5,12,29,.86),rgba(8,5,22,.84));padding:14px 14px 12px;clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px));transition:.18s}.mem-card:hover{border-color:var(--cyan);transform:translateY(-1px);box-shadow:0 0 24px rgba(102,252,241,.13)}.mem-header{display:flex;gap:8px;align-items:center;margin-bottom:9px}.type-badge{border:1px solid currentColor;padding:3px 8px;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase}.badge-world{color:var(--green)}.badge-experience{color:var(--cyan2)}.badge-observation{color:var(--violet)}.badge-preference{color:var(--amber)}.badge-lesson{color:var(--red)}.badge-other{color:var(--muted)}.mem-agent{color:var(--muted);font-size:.78rem;flex:1}.mem-date{color:var(--dim);font-size:.72rem}.mem-content{line-height:1.45;color:#d8f8ff;font-size:.94rem}.mem-footer{display:flex;align-items:center;gap:10px;margin-top:12px}.mem-meta{flex:1;color:var(--dim);font-size:.76rem}.imp-bar{display:inline-block;width:74px;height:5px;background:#08101e;margin-left:6px;vertical-align:middle;border:1px solid rgba(102,252,241,.14)}.imp-fill{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--violet))}.del-btn,.action{border:1px solid rgba(255,84,112,.4);background:rgba(255,84,112,.06);color:#ff8ca0;padding:7px 10px;text-transform:uppercase;letter-spacing:.1em;font-size:.7rem}.action{border-color:rgba(102,252,241,.35);background:rgba(102,252,241,.08);color:var(--cyan)}.action:hover,.del-btn:hover{filter:brightness(1.25);box-shadow:0 0 18px currentColor}.pagination{display:flex;justify-content:center;gap:10px;align-items:center}.page-btn{border:1px solid var(--line);background:rgba(102,252,241,.06);color:var(--cyan);padding:8px 14px}.page-btn:disabled{opacity:.35}.page-info{color:var(--muted);font-size:.8rem}.agentsTab{grid-template-columns:360px 1fr;gap:16px}.agentCards{overflow:auto;display:grid;gap:10px}.agentCard{border:1px solid rgba(185,103,255,.22);background:rgba(9,8,29,.76);padding:13px}.agentCard h4{margin:0;color:var(--text)}.agentMeta{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px;color:var(--muted);font-size:.78rem}.deviceChip{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(102,252,241,.28);background:rgba(102,252,241,.07);color:var(--cyan);padding:3px 7px;margin-top:7px;font-size:.68rem;text-transform:uppercase;letter-spacing:.1em}.deviceChip.unknown{color:var(--muted);border-color:rgba(110,140,155,.25);background:rgba(110,140,155,.05)}.console{grid-template-rows:auto 1fr;gap:12px}.consoleForm{display:grid;grid-template-columns:1fr 150px;gap:10px}.consoleOut{background:#02040b;border:1px solid rgba(102,252,241,.22);padding:14px;overflow:auto;color:#a7f7f1;font-family:"Share Tech Mono","Courier New",monospace;white-space:pre-wrap}.ticker{grid-column:2;border:1px solid var(--line2);background:rgba(3,6,18,.82);color:var(--muted);padding:9px 12px;overflow:hidden;font-size:.78rem}.ticker-event{color:var(--cyan);animation:slideIn .35s ease}@keyframes slideIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}.empty,.loading{color:var(--muted);text-align:center;padding:30px;border:1px dashed rgba(102,252,241,.18)}::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:#02040b}::-webkit-scrollbar-thumb{background:linear-gradient(var(--cyan),var(--violet));border-radius:8px}@media(max-width:950px){body{overflow:auto}.app{height:auto;min-height:100%;grid-template-columns:1fr;grid-template-rows:auto 1fr auto}.rail{grid-row:auto}.ticker{grid-column:1}.statGrid,.overviewGrid,.agentsTab,.tools,.consoleForm{grid-template-columns:1fr}.tabs.active{display:block}.tabs>*{margin-bottom:12px}}
</style>
</head>
<body>
<div class="app">
  <aside class="rail shell">
    <div class="brand"><div class="orb"></div><div class="kicker">Unified Memory Core</div><h1>NEXUS</h1><div class="sub">semantic · lexical · graph · temporal recall matrix</div></div>
    <nav class="nav">
      <button class="active" data-tab="overview" onclick="switchTab('overview')">◇ Overview</button>
      <button data-tab="vault" onclick="switchTab('vault')">▣ Memory Vault</button>
      <button data-tab="mind" onclick="switchTab('mind')">◉ Living Mind</button>
      <button data-tab="agents" onclick="switchTab('agents')">⌬ Agent Registry</button>
      <button data-tab="sessions" onclick="switchTab('sessions')">◷ Sessions</button>
      <button data-tab="recalllab" onclick="switchTab('recalllab')">◬ Recall Lab</button>
      <button data-tab="ops" onclick="switchTab('ops')">⚡ Operations</button>
      <button data-tab="quality" onclick="switchTab('quality')">◍ Memory Quality</button>
      <button data-tab="console" onclick="switchTab('console')">⌁ Neural Console</button>
    </nav>
    <section class="sidePanel"><h3 class="sideTitle">Agent Channels</h3><div class="agentList" id="agent-list"></div></section>
  </aside>

  <main class="main shell">
    <header class="topbar"><div class="titleBlock"><div class="eyebrow" id="tab-eyebrow">Command Overview</div><h2 id="tab-title">Memory Constellation</h2></div><div class="status"><span class="dot"></span><span id="live-count">connecting</span></div></header>

    <section id="tab-overview" class="tabs overview active">
      <div class="statGrid">
        <div class="stat"><div class="lbl">Memories</div><div class="val" id="s-memories">…</div><div class="sig">MEM/IDX</div></div>
        <div class="stat"><div class="lbl">Agents</div><div class="val" id="s-agents">…</div><div class="sig">NODE/LINK</div></div>
        <div class="stat"><div class="lbl">Entities</div><div class="val" id="s-entities">…</div><div class="sig">GRAPH/ENT</div></div>
        <div class="stat"><div class="lbl">Rules</div><div class="val" id="s-conclusions">…</div><div class="sig">REMEMBER</div></div>
      </div>
      <div class="overviewGrid">
        <div class="panel"><h3>Memory Type Spectrum</h3><div class="type-pills" id="type-pills"></div></div>
        <div class="panel scanner"><div class="scannerText">Live Memory Lattice · Awaiting Event Pulse</div></div>
      </div>
    </section>

    <section id="tab-vault" class="tabs vault">
      <div class="tools"><input class="field" type="text" id="search-input" placeholder="Search the memory lattice…"><select class="field" id="type-filter"><option value="">All types</option><option value="world">World</option><option value="experience">Experience</option><option value="observation">Observation</option><option value="preference">Preference</option><option value="lesson">Lesson</option></select><button class="action" onclick="loadMemories()">Scan</button></div>
      <div class="memories" id="memories"></div>
      <div class="pagination" id="pagination" style="display:none"><button class="page-btn" id="prev-btn" onclick="changePage(-1)" disabled>← Prev</button><span class="page-info" id="page-info"></span><button class="page-btn" id="next-btn" onclick="changePage(1)" disabled>Next →</button></div>
    </section>

    <section id="tab-mind" class="tabs">
      <div class="statGrid">
        <div class="stat"><div class="lbl">Patterns</div><div class="val" id="m-patterns">…</div><div class="sig">LEARNED</div></div>
        <div class="stat"><div class="lbl">Opinions</div><div class="val" id="m-opinions">…</div><div class="sig">HELD</div></div>
        <div class="stat"><div class="lbl">Conversations</div><div class="val" id="m-conversations">…</div><div class="sig">ACTIVE</div></div>
        <div class="stat"><div class="lbl">Relationships</div><div class="val" id="m-relationships">…</div><div class="sig">KNOWN</div></div>
      </div>
      <div class="overviewGrid" style="grid-template-columns:1fr 1fr;gap:16px">
        <div class="panel" style="min-height:140px"><h3>Mind Identity</h3><pre class="consoleOut" id="mind-identity" style="white-space:pre-wrap;max-height:280px;overflow:auto">Loading mind…</pre></div>
        <div class="panel" style="min-height:140px"><h3>Active Opinions</h3><div class="consoleOut" id="mind-opinions" style="max-height:280px;overflow:auto">Loading…</div></div>
      </div>
      <div class="overviewGrid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
        <div class="panel" style="min-height:160px"><h3>Learned Patterns (recent)</h3><div class="consoleOut" id="mind-patterns" style="max-height:280px;overflow:auto">Loading…</div></div>
        <div class="panel" style="min-height:160px"><h3>Relationships</h3><div class="consoleOut" id="mind-relationships" style="max-height:280px;overflow:auto">Loading…</div></div>
      </div>
      <div class="panel" style="margin-top:16px"><h3>Ask the Mind</h3>
        <div class="consoleForm">
          <input class="field" type="text" id="mind-question" placeholder="What do you know about X?">
          <select class="field" id="mind-depth"><option value="fast">fast</option><option value="standard" selected>standard</option><option value="deep">deep</option></select>
          <button class="action" onclick="askMind()">Think</button>
        </div>
        <pre class="consoleOut" id="mind-answer" style="min-height:120px;max-height:400px;overflow:auto;white-space:pre-wrap">Ask the mind a question to see reasoned output here.</pre>
      </div>
    </section>

    <section id="tab-agents" class="tabs agentsTab"><div class="panel"><h3>Selected Channel</h3><div id="agent-detail" class="consoleOut">Select an agent channel to inspect.</div></div><div class="agentCards" id="agent-cards"></div></section>

    <section id="tab-sessions" class="tabs agentsTab"><div class="panel"><h3>Session Timeline</h3><div id="session-list" class="consoleOut">Loading sessions…</div></div><div class="panel"><h3>Raw Messages</h3><div id="session-detail" class="consoleOut">Select a session to inspect messages and provenance context.</div></div></section>

    <section id="tab-recalllab" class="tabs console"><div class="consoleForm"><input class="field" id="lab-query" placeholder="Compare recall modes…"><select class="field" id="lab-compare-agent"><option value="">No comparison</option></select><button class="action" onclick="runRecallLab()">Run Lab</button><button class="action" onclick="copyRecallReport()">Copy Report</button></div><div class="overviewGrid"><div class="panel"><h3>Vector</h3><div class="consoleOut" id="lab-vector">—</div></div><div class="panel"><h3>Lexical</h3><div class="consoleOut" id="lab-lexical">—</div></div><div class="panel"><h3>Graph</h3><div class="consoleOut" id="lab-graph">—</div></div><div class="panel"><h3>Temporal</h3><div class="consoleOut" id="lab-temporal">—</div></div></div><div class="panel"><h3>Fused / Reranked</h3><div class="consoleOut" id="lab-fused">NEXUS:// recall lab ready</div></div><div class="panel"><h3>Agent Comparison</h3><div class="consoleOut" id="lab-compare">Select an agent to compare against the active channel.</div></div></section>

    <section id="tab-ops" class="tabs console"><div class="statGrid"><div class="stat"><div class="lbl">Sessions</div><div class="val" id="o-sessions">…</div><div class="sig">RAW/CTX</div></div><div class="stat"><div class="lbl">Messages</div><div class="val" id="o-messages">…</div><div class="sig">EVENT/LOG</div></div><div class="stat"><div class="lbl">RTK Saved</div><div class="val" id="o-rtk-tokens">…</div><div class="sig">TOKENS</div></div><div class="stat"><div class="lbl">RTK Failures</div><div class="val" id="o-rtk-fail">…</div><div class="sig">24H</div></div></div><div class="overviewGrid"><div class="panel"><h3>RTK By Agent</h3><div class="consoleOut" id="ops-rtk-agents">Loading…</div></div><div class="panel"><h3>Recent Events</h3><div class="consoleOut" id="ops-events">Loading…</div></div></div></section>

    <section id="tab-quality" class="tabs console"><div class="statGrid"><div class="stat"><div class="lbl">Active Memories</div><div class="val" id="q-total">…</div><div class="sig">LIVE</div></div><div class="stat"><div class="lbl">Avg Confidence</div><div class="val" id="q-confidence">…</div><div class="sig">0–1</div></div><div class="stat"><div class="lbl">Avg Importance</div><div class="val" id="q-importance">…</div><div class="sig">0–1</div></div><div class="stat"><div class="lbl">Superseded</div><div class="val" id="q-superseded">…</div><div class="sig">REPLACED</div></div></div><div class="overviewGrid"><div class="panel"><h3>Confidence Distribution</h3><div id="q-dist" style="display:flex;flex-direction:column;gap:8px;margin-top:8px">Loading…</div></div><div class="panel"><h3>Trust Signals</h3><div class="consoleOut" id="q-trust">Loading…</div></div></div><div class="overviewGrid"><div class="panel"><h3>Memories By Type</h3><div class="type-pills" id="q-types">Loading…</div></div><div class="panel"><h3>Top Agents</h3><div class="consoleOut" id="q-agents">Loading…</div></div></div></section>

    <section id="tab-console" class="tabs console"><div class="consoleForm"><input class="field" id="recall-query" placeholder="Ask Nexus recall…"><button class="action" onclick="runRecall()">Recall</button></div><pre class="consoleOut" id="console-output">NEXUS:// console online\nType a query and run recall.</pre></section>
  </main>

  <div class="ticker" id="ticker">⚡ Establishing live telemetry…</div>
</div>

<script>
const TOKEN = "__NEXUS_TOKEN__";
const LIMIT = 20;
let state = { agent:null, type:"", query:"", offset:0, total:0, liveCount:0, agents:[], recallReport:null };
const tabNames = {overview:["Command Overview","Memory Constellation"],vault:["Memory Vault","Recall Archive"],mind:["Living Mind","Reasoning Layer · Identity · Opinions"],agents:["Agent Registry","Channel Topology"],sessions:["Sessions","Raw Timeline · Provenance"],recalllab:["Recall Lab","Mode Comparison · Fusion"],ops:["Operations","RTK · Sessions · Telemetry"],quality:["Memory Quality","Health · Confidence · Decay"],console:["Neural Console","Direct Recall Interface"]};
function apiFetch(path, opts={}){return fetch(path,{...opts,headers:{Authorization:"Bearer "+TOKEN,"Content-Type":"application/json",...(opts.headers||{})}}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json();});}
function escHtml(s){return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function deviceLabel(a){return a?.device||a?.hostname||a?.source||"Unknown Device";}
function deviceClass(a){return (a?.device||a?.hostname||a?.source)?"deviceChip":"deviceChip unknown";}
function switchTab(tab){document.querySelectorAll('.tabs').forEach(e=>e.classList.remove('active'));document.getElementById('tab-'+tab).classList.add('active');document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));document.getElementById('tab-eyebrow').textContent=tabNames[tab][0];document.getElementById('tab-title').textContent=tabNames[tab][1];if(tab==='vault')loadMemories();if(tab==='mind')loadMind();if(tab==='agents')renderAgentCards();if(tab==='sessions')loadSessions();if(tab==='ops')loadOps();if(tab==='quality')loadQuality();}
function typeBadgeClass(t){return ({world:'badge-world',experience:'badge-experience',observation:'badge-observation',preference:'badge-preference',lesson:'badge-lesson'}[t]||'badge-other');}
function fmtDate(dt){if(!dt)return'';const d=new Date(dt);return d.toLocaleDateString()+" "+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}
function renderMemory(m){const imp=Math.round((m.importance||0)*100);return `<div class="mem-card" id="mc-${m.id}"><div class="mem-header"><span class="type-badge ${typeBadgeClass(m.memory_type)}">${escHtml(m.memory_type)}</span><span class="mem-agent">${escHtml(m.agent_name||m.agent_id||'?')}</span><span class="mem-date">${fmtDate(m.created_at)}</span></div><div class="mem-content">${escHtml(m.content)}</div><div class="mem-footer"><span class="mem-meta">importance ${imp}% <span class="imp-bar"><span class="imp-fill" style="width:${imp}%"></span></span> · accessed ${m.access_count||0}x ${m.confirmed_count?' · ✓ '+m.confirmed_count:''}${m.contradicted_count?' · ⚠ '+m.contradicted_count:''}</span><button class="del-btn" onclick="deleteMemory('${m.id}')">Delete</button></div></div>`;}
async function loadMemories(){const el=document.getElementById('memories');el.innerHTML='<div class="loading">Scanning archive…</div>';const params=new URLSearchParams({limit:LIMIT,offset:state.offset});if(state.query)params.set('q',state.query);if(state.agent)params.set('agent',state.agent);if(state.type)params.set('type',state.type);try{const data=await apiFetch('/v1/browse/memories?'+params);state.total=data.total;if(!data.memories.length){el.innerHTML='<div class="empty">No memory signatures found.</div>';document.getElementById('pagination').style.display='none';return;}el.innerHTML=data.memories.map(renderMemory).join('');updatePagination();}catch(e){el.innerHTML='<div class="empty">Archive scan failed: '+escHtml(e.message)+'</div>';}}
function updatePagination(){const pages=Math.ceil(state.total/LIMIT);const cur=Math.floor(state.offset/LIMIT)+1;const p=document.getElementById('pagination');if(pages<=1){p.style.display='none';return;}p.style.display='flex';document.getElementById('page-info').textContent=`Sector ${cur}/${pages} · ${state.total} records`;document.getElementById('prev-btn').disabled=state.offset===0;document.getElementById('next-btn').disabled=state.offset+LIMIT>=state.total;}
function changePage(dir){state.offset=Math.max(0,state.offset+dir*LIMIT);loadMemories();}
async function loadStats(){try{const d=await apiFetch('/v1/browse/stats');document.getElementById('s-memories').textContent=d.total_memories;document.getElementById('s-agents').textContent=d.total_agents;document.getElementById('s-entities').textContent=d.total_entities;document.getElementById('s-conclusions').textContent=d.total_conclusions;document.getElementById('type-pills').innerHTML=(d.by_type||[]).map(t=>`<span class="pill${state.type===t.memory_type?' active':''}" onclick="filterType('${t.memory_type}')">${escHtml(t.memory_type)} <b>${t.count}</b></span>`).join('');}catch(e){}}


async function loadMind(){try{const d=await apiFetch('/v1/mind/dashboard?mind_id=default');document.getElementById('m-patterns').textContent=d.stats.patterns_learned;document.getElementById('m-opinions').textContent=d.stats.opinions_held;document.getElementById('m-conversations').textContent=d.stats.active_conversations;document.getElementById('m-relationships').textContent=d.stats.relationships;document.getElementById('mind-identity').textContent=d.self_description;const ops=d.opinions||{};const opLines=Object.keys(ops).length?Object.entries(ops).map(([t,o])=>`  ${t.padEnd(28)}  ${(o.stance||'?').padEnd(9)}  strength=${(o.strength||0).toFixed(2)}  evidence=${o.evidence_count||0}`).join('\n'):'  No opinions held yet — ask the mind a question to form one.';document.getElementById('mind-opinions').textContent=opLines;const pats=(d.identity&&d.identity.learned_patterns)||[];const patLines=pats.length?pats.slice(-10).reverse().map(p=>`  · [imp ${(p.importance||0).toFixed(2)}] ${escHtml(p.description)}`).join('\n'):'  No patterns learned yet.';document.getElementById('mind-patterns').textContent=patLines;const rels=d.relationships||{};const relLines=Object.keys(rels).length?Object.entries(rels).map(([a,r])=>`  ${a.padEnd(20)}  trust=${(r.trust_level||0).toFixed(2)}  interactions=${r.interaction_count||0}  style=${r.communication_style||'-'}`).join('\n'):'  No agent relationships yet.';document.getElementById('mind-relationships').textContent=relLines;}catch(e){document.getElementById('mind-identity').textContent='Mind load failed: '+e.message;}}

async function askMind(){const q=document.getElementById('mind-question').value.trim();if(!q)return;const depth=document.getElementById('mind-depth').value;const out=document.getElementById('mind-answer');out.textContent='MIND:// thinking...';try{const d=await apiFetch('/v1/mind/think',{method:'POST',body:JSON.stringify({mind_id:'default',question:q,reasoning_depth:depth})});let out_text='';if(d.answer)out_text+=d.answer+'\n\n';if(d.clarifying_question)out_text+='[Question back: '+d.clarifying_question+']\n\n';out_text+=`[confidence: ${(d.confidence||0).toFixed(2)} | memories: ${(d.memories_cited||[]).length} | proactive items: ${(d.proactive_context||[]).length}]\n`;if((d.proactive_context||[]).length){out_text+='\nProactive context:\n';d.proactive_context.forEach(item=>{out_text+=`  - [${item.type||'?'}] ${item.content||''} (relevance ${(item.relevance||0).toFixed(2)})\n`;});}if((d.opinions_expressed||[]).length){out_text+='\nMy take:\n';d.opinions_expressed.forEach(op=>{out_text+=`  - ${op.topic}: ${op.stance} (strength ${(op.strength||0).toFixed(2)})\n`;});}out.textContent=out_text;}catch(e){out.textContent='MIND:// think failed: '+e.message;}}
async function loadOps(){try{const [m,r]=await Promise.all([apiFetch('/v1/admin/metrics'),apiFetch('/v1/admin/rtk/summary')]);document.getElementById('o-sessions').textContent=m.totals?.sessions??0;document.getElementById('o-messages').textContent=m.totals?.messages??0;document.getElementById('o-rtk-tokens').textContent=r.tokens_saved_estimate??0;document.getElementById('o-rtk-fail').textContent=r.failures??0;document.getElementById('ops-rtk-agents').textContent=(r.by_agent||[]).map(a=>`${a.agent_id}: ${a.tokens_saved_estimate} tokens · ${a.count} cmds · ${a.failures} failures`).join('\n')||'No RTK telemetry yet.';document.getElementById('ops-events').textContent=(m.recent_events||[]).slice(0,12).map(e=>`${fmtDate(e.created_at)} ${e.action} ${e.actor||''}`).join('\n')||'No recent events.';}catch(e){document.getElementById('ops-events').textContent='Operations load failed: '+e.message;}}
async function loadQuality(){try{const d=await apiFetch('/v1/admin/memory-quality');document.getElementById('q-total').textContent=d.total_memories??0;document.getElementById('q-confidence').textContent=(d.avg_confidence||0).toFixed(2);document.getElementById('q-importance').textContent=(d.avg_importance||0).toFixed(2);document.getElementById('q-superseded').textContent=d.superseded_count??0;const dist=d.confidence_distribution||{};const max=Math.max(1,...Object.values(dist));const colors={'0.0-0.2':'var(--red,#ff5d73)','0.2-0.4':'#ff9f45','0.4-0.6':'#ffd24a','0.6-0.8':'#66fcf1','0.8-1.0':'var(--green)'};document.getElementById('q-dist').innerHTML=Object.entries(dist).map(([band,n])=>`<div style="display:grid;grid-template-columns:64px 1fr 48px;gap:8px;align-items:center"><span style="font-size:.72rem;color:var(--muted)">${band}</span><span style="background:rgba(255,255,255,.05);height:14px;position:relative"><span style="position:absolute;inset:0 auto 0 0;width:${Math.round(n/max*100)}%;background:${colors[band]||'var(--cyan)'};opacity:.8"></span></span><span style="font-variant-numeric:tabular-nums;text-align:right">${n}</span></div>`).join('')||'No data.';document.getElementById('q-trust').textContent=`Expired (past valid_until): ${d.expired_count??0}\nConfirmations total:        ${d.total_confirmed??0}\nContradictions total:       ${d.total_contradicted??0}`;document.getElementById('q-types').innerHTML=Object.entries(d.memories_by_type||{}).map(([t,n])=>`<span class="pill">${escHtml(t||'?')} <b>${n}</b></span>`).join('')||'No data.';document.getElementById('q-agents').textContent=(d.top_agents_by_memory_count||[]).map(a=>`${(a.agent||'?').padEnd(22)} ${a.count}`).join('\n')||'No agents.';}catch(e){document.getElementById('q-dist').textContent='Memory quality load failed: '+e.message;}}
async function loadSessions(){const el=document.getElementById('session-list');el.textContent='Loading sessions…';try{const sessions=await apiFetch('/v1/sessions?limit=50');el.innerHTML=(sessions||[]).map(s=>`<div class="agent-item" onclick="showSession('${s.id}')"><span><b>${escHtml(s.title||s.id.slice(0,8))}</b><br><span class="deviceChip">${escHtml(s.agent_id||'?')} · ${escHtml(s.project_key||'-')} · ${s.message_count||0} msgs</span></span><span class="agent-count">${s.ended_at?'✓':'●'}</span></div>`).join('')||'<div class="empty">No sessions archived yet.</div>';}catch(e){el.textContent='Session load failed: '+e.message;}}
async function showSession(id){const el=document.getElementById('session-detail');el.textContent='Loading session '+id+'…';try{const s=await apiFetch('/v1/sessions/'+encodeURIComponent(id)+'?limit=200');el.textContent=`SESSION: ${s.id}
AGENT: ${s.agent_id}
PROJECT: ${s.project_key||'-'}
TITLE: ${s.title||'-'}
STARTED: ${fmtDate(s.started_at)}
ENDED: ${fmtDate(s.ended_at)||'active'}
MESSAGES: ${(s.messages||[]).length}

${(s.messages||[]).map(m=>`[${fmtDate(m.created_at)}] ${m.role} · ~${m.token_estimate||0} tokens · ${m.id}\n${m.content}`).join('\n\n---\n\n')||'(no messages)'}`;}catch(e){el.textContent='Session detail failed: '+e.message;}}
function labList(items){return (items||[]).map((m,i)=>{const score=Math.max(0,Math.min(100,Math.round((m.score||0)*100)));const matched=(m.matched_by||[]).join(', ')||'recall';return `<div class="mem-card"><div class="mem-header"><span class="type-badge ${typeBadgeClass(m.memory_type)}">${escHtml(m.memory_type)}</span><span class="mem-meta">#${i+1} score=${Number(m.score||0).toFixed(3)} imp=${Math.round((m.importance||0)*100)}%</span></div><div class="imp-bar"><span class="imp-fill" style="width:${score}%"></span></div><div class="mem-meta">matched: ${escHtml(matched)} · trust ✓${m.confirmed_count||0} ⚠${m.contradicted_count||0}</div><div class="mem-content">${escHtml(m.content)}</div><div class="mem-footer"><button class="del-btn" onclick="feedbackMemory('${m.id}','confirm')">Useful ✓</button><button class="del-btn" onclick="feedbackMemory('${m.id}','contradict')">Not useful ⚠</button><button class="del-btn" onclick="navigator.clipboard?.writeText('${m.id}')">Copy ID</button></div></div>`}).join('')||'<div class="empty">No results</div>';}
async function feedbackMemory(id,kind){try{await apiFetch('/v1/memory/'+id+'/'+(kind==='confirm'?'confirm':'contradict'),{method:'POST'});const out=document.getElementById('lab-fused');out.insertAdjacentHTML('afterbegin',`<div class="empty">Feedback saved: ${kind} ${id.slice(0,8)}…</div>`);}catch(e){alert('Feedback failed: '+e.message);}}
async function runRecallLab(){const q=document.getElementById('lab-query').value.trim();if(!q)return;['vector','lexical','graph','temporal'].forEach(m=>document.getElementById('lab-'+m).innerHTML='<div class="loading">running…</div>');document.getElementById('lab-fused').textContent='fusing…';try{const payload={query:q,agent_id:state.agent,limit:8,search_modes:['vector','lexical','graph','temporal']};const d=await apiFetch('/v1/memory/recall/debug',{method:'POST',body:JSON.stringify(payload)});state.recallReport=d;['vector','lexical','graph','temporal'].forEach(m=>document.getElementById('lab-'+m).innerHTML=labList(d.per_mode?.[m]||[]));document.getElementById('lab-fused').innerHTML=`<div class="consoleOut">QUERY: ${escHtml(d.query)}\nAGENT: ${escHtml(d.agent_id||'all')}\nEXPANDED: ${escHtml(d.expanded_query)}\nFUSION: ${escHtml(d.fusion)}\nMODE COUNTS: ${escHtml(JSON.stringify(d.explanation?.mode_counts||{}))}</div><h3>Fused</h3>${labList(d.fused)}<h3>Reranked</h3>${labList(d.reranked)}`;const ca=document.getElementById('lab-compare-agent').value;if(ca){const c=await apiFetch('/v1/memory/recall/debug',{method:'POST',body:JSON.stringify({...payload,agent_id:ca})});document.getElementById('lab-compare').innerHTML=`<div class="consoleOut">BASE: ${escHtml(state.agent||'all')} · COMPARE: ${escHtml(ca)}\nBASE TOP: ${(d.reranked||[])[0]?.id||'-'}\nCOMPARE TOP: ${(c.reranked||[])[0]?.id||'-'}\nCOMPARE COUNTS: ${escHtml(JSON.stringify(c.explanation?.mode_counts||{}))}</div>${labList(c.reranked)}`;}else{document.getElementById('lab-compare').textContent='Select an agent to compare against the active channel.';}}catch(e){document.getElementById('lab-fused').textContent='Recall lab failed: '+e.message;}}
function copyRecallReport(){if(!state.recallReport){alert('Run Recall Lab first.');return;}navigator.clipboard?.writeText(JSON.stringify(state.recallReport,null,2));}
async function loadAgents(){try{const d=await apiFetch('/v1/browse/agents');state.agents=d.agents||[];const all=`<div class="agent-item${!state.agent?' active':''}" onclick="filterAgent(null)"><span>All channels</span><span class="agent-count">Σ</span></div>`;document.getElementById('agent-list').innerHTML=all+state.agents.map(a=>`<div class="agent-item${state.agent===a.name?' active':''}" onclick="filterAgent('${escHtml(a.name)}')"><span title="${escHtml(a.name)}"><span>${escHtml(a.name.length>18?a.name.slice(0,18)+'…':a.name)}</span><br><span class="${deviceClass(a)}">⌁ ${escHtml(deviceLabel(a))}</span></span><span class="agent-count">${a.memory_count}</span></div>`).join('');const sel=document.getElementById('lab-compare-agent');if(sel)sel.innerHTML='<option value="">No comparison</option>'+state.agents.map(a=>`<option value="${escHtml(a.name)}">${escHtml(a.name)}</option>`).join('');renderAgentCards();}catch(e){}}
function renderAgentCards(){const el=document.getElementById('agent-cards');if(!el)return;el.innerHTML=(state.agents||[]).map(a=>`<article class="agentCard" onclick="showAgent('${escHtml(a.name)}')"><h4>${escHtml(a.name)}</h4><div class="${deviceClass(a)}">⌁ ${escHtml(deviceLabel(a))}</div><div class="agentMeta"><span>mem ${a.memory_count}</span><span>ent ${a.entity_count}</span><span>rules ${a.conclusion_count}</span><span>sessions ${a.session_count||0}</span><span>host ${escHtml(a.hostname||'unknown')}</span><span>source ${escHtml(a.source||'unknown')}</span><span>model ${escHtml(a.model||'unknown')}</span><span>${fmtDate(a.last_active)}</span></div></article>`).join('')||'<div class="empty">No agents registered.</div>';}
async function showAgent(name){const el=document.getElementById('agent-detail');const a=state.agents.find(x=>x.name===name);if(!a){el.textContent='No channel selected.';return;}el.textContent='Loading agent card…';try{const c=await apiFetch('/v1/agents/'+encodeURIComponent(name)+'/card');el.textContent=`AGENT CARD: ${c.display_name||name}
CONFIDENCE: ${Math.round((c.confidence||0)*100)}%
MODEL: ${c.model||a.model||'unknown'}
MEMORIES: ${c.memory_count} · ENTITIES: ${c.entity_count} · CONCLUSIONS: ${c.conclusion_count} · SUMMARIES: ${c.summary_count}
TRUST: ✓ ${c.confirmed_count||0} · ⚠ ${c.contradicted_count||0}
SOURCES: ${JSON.stringify(c.source_counts||{})}
TYPES: ${JSON.stringify(c.top_memory_types||{})}

REPRESENTATION:
${c.representation||'(none yet)'}

CONCLUSIONS:
${(c.conclusions||[]).map(x=>'• '+x).join('\n')||'(none)'}

TOP MEMORIES:
${(c.recent_memories||[]).map(m=>`• [${m.memory_type}] ${m.content}`).join('\n\n')||'(none)'}
`;}catch(e){el.textContent=`AGENT: ${a.name}
DEVICE: ${deviceLabel(a)}
HOST: ${a.hostname||'unknown'}
SOURCE: ${a.source||'unknown'}
MODEL: ${a.model||'unknown'}
MEMORIES: ${a.memory_count}
ENTITIES: ${a.entity_count}
RULES: ${a.conclusion_count}
LAST ACTIVE: ${fmtDate(a.last_active)}

Agent card load failed: ${e.message}

RAW:
${JSON.stringify(a,null,2)}`;}}
function filterAgent(name){state.agent=name;state.offset=0;loadAgents();loadMemories();showAgent(name);switchTab('vault');}
function filterType(type){state.type=state.type===type?'':type;document.getElementById('type-filter').value=state.type;state.offset=0;loadStats();loadMemories();switchTab('vault');}
async function deleteMemory(id){if(!confirm('Purge this memory record?'))return;try{await apiFetch('/v1/browse/memories/'+id,{method:'DELETE'});document.getElementById('mc-'+id)?.remove();loadStats();loadAgents();}catch(e){alert('Delete failed: '+e.message);}}
async function runRecall(){const q=document.getElementById('recall-query').value.trim();if(!q)return;const out=document.getElementById('console-output');out.textContent='NEXUS:// recalling…';try{const d=await apiFetch('/v1/memory/recall',{method:'POST',body:JSON.stringify({query:q,agent_id:state.agent,limit:8})});out.textContent='NEXUS:// recall complete\\nModes: '+d.modes_used.join(', ')+'\\n\\n'+d.results.map((m,i)=>`${i+1}. [${m.memory_type}] score=${Number(m.score||0).toFixed(3)}\\n${m.content}`).join('\\n\\n');}catch(e){out.textContent='NEXUS:// recall failed '+e.message;}}
let searchTimer;document.getElementById('search-input').addEventListener('input',e=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.query=e.target.value.trim();state.offset=0;loadMemories();},300);});document.getElementById('type-filter').addEventListener('change',e=>{state.type=e.target.value;state.offset=0;loadStats();loadMemories();});
function connectSSE(){const ticker=document.getElementById('ticker');const es=new EventSource('/v1/stream?'+new URLSearchParams({Authorization:'Bearer '+TOKEN}));es.addEventListener('connected',()=>{ticker.innerHTML='⚡ Live telemetry connected';document.getElementById('live-count').textContent='connected';});es.addEventListener('memory',e=>{const d=JSON.parse(e.data);state.liveCount++;document.getElementById('live-count').textContent=state.liveCount+' new';ticker.innerHTML=`<span class="ticker-event">⚡ [${escHtml(d.memory_type||'memory')}] <b>${escHtml(d.agent_name||'?')}:</b> ${escHtml((d.content||'').slice(0,140))}</span>`;if(state.offset===0&&!state.query&&!state.type&&!state.agent)loadMemories();loadStats();loadAgents();});es.onerror=()=>{ticker.innerHTML='⚡ telemetry interrupted — reconnecting…';document.getElementById('live-count').textContent='reconnecting';es.close();setTimeout(connectSSE,5000);};}
function loadAll(){loadStats();loadAgents();loadMemories();loadOps();loadMind();}
loadAll();connectSSE();setInterval(loadAll,30000);
// Live mind refresh — every 5s, ping the mind to keep state hot
setInterval(loadMind,5000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    _verify_key(request)
    dashboard_token = _make_dashboard_token()
    html = _DASHBOARD_HTML.replace("__NEXUS_TOKEN__", dashboard_token)
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.nexus_port, reload=False)
