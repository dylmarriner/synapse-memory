"""Active memory push daemon.

Subscribes to the Redis `nexus:push` stream. On each event, builds a
fresh context snapshot for the affected agent and delivers it to all
registered adapters.

Events published to the stream:
  {"agent_id": "...", "event": "memory_saved|session_ended|preference_saved", "timestamp": "..."}

The daemon runs as a background asyncio task started in app/main.py.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.db import SessionLocal
from app.push.registry import get_adapters
from app.push.snapshot import build_snapshot

log = logging.getLogger("nexus.push.daemon")

_STREAM_KEY = "nexus:push"
_GROUP = "nexus-push-workers"
_CONSUMER = "daemon-0"
_BLOCK_MS = 5000
_MIN_INTERVAL_SECS = 30  # don't push same agent more than once per 30s


class PushDaemon:
    def __init__(self, redis):
        self._publish_redis = redis  # shared client for publishing only
        self._last_push: dict[str, float] = {}
        self._running = False

    async def start(self):
        self._running = True
        # Dedicated connection for blocking xreadgroup — socket_timeout=None required
        self._redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_timeout=None, socket_connect_timeout=5.0,
        )
        await self._ensure_stream()
        log.info("Push daemon started — watching %s", _STREAM_KEY)
        while self._running:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Push daemon error: %s", e)
                await asyncio.sleep(5)
        await self._redis.aclose()

    def stop(self):
        self._running = False

    async def _ensure_stream(self):
        try:
            await self._redis.xgroup_create(_STREAM_KEY, _GROUP, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

    async def _process_batch(self):
        results = await self._redis.xreadgroup(
            _GROUP, _CONSUMER, {_STREAM_KEY: ">"}, count=10, block=_BLOCK_MS
        )
        if not results:
            return
        for _stream, messages in results:
            for msg_id, fields in messages:
                try:
                    await self._handle(fields)
                except Exception as e:
                    log.error("Failed to handle push event %s: %s", msg_id, e)
                finally:
                    await self._redis.xack(_STREAM_KEY, _GROUP, msg_id)

    async def _handle(self, fields: dict):
        agent_id = fields.get("agent_id")
        if not agent_id:
            return

        # Rate-limit: skip if we pushed recently
        now = datetime.now(timezone.utc).timestamp()
        if now - self._last_push.get(agent_id, 0) < _MIN_INTERVAL_SECS:
            log.debug("Skipping push for %s (rate limited)", agent_id)
            return

        adapters = await get_adapters(self._redis, agent_id)
        if not adapters:
            return

        async with SessionLocal() as db:
            snapshot = await build_snapshot(db, agent_id)

        meta = {
            "event": fields.get("event", "memory_update"),
            "timestamp": fields.get("timestamp"),
        }

        results = await asyncio.gather(
            *[a.push(agent_id, snapshot, meta) for a in adapters],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if r is True)
        log.info("Pushed context for %s: %d/%d adapters succeeded", agent_id, ok, len(adapters))
        self._last_push[agent_id] = now


async def publish_push_event(redis, agent_id: str, event: str = "memory_saved"):
    """Publish a push event. Called from worker/ingest after saves."""
    try:
        await redis.xadd(_STREAM_KEY, {
            "agent_id": agent_id,
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, maxlen=1000)
    except Exception as e:
        log.warning("Failed to publish push event: %s", e)
