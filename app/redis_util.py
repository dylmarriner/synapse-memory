"""Redis connection helper with embedded (fakeredis) support.

In normal operation every component connects to a real Redis via
``settings.redis_url``.  In embedded mode (``EMBEDDED_MODE=true`` or a
``fakeredis://`` URL) we hand out clients backed by a single in-process
fakeredis server so the API and the in-process worker share one queue
without needing a Redis container.
"""

from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("nexus.redis")

# Shared fakeredis server — created once so every in-process client sees the
# same keyspace (separate FakeRedis() instances do NOT share data otherwise).
_fake_server = None


def _is_embedded() -> bool:
    return settings.embedded_mode or settings.redis_url.startswith("fakeredis://")


def make_redis(*, decode_responses: bool = False, **kwargs):
    """Return an async Redis client — real or fakeredis depending on mode."""
    if _is_embedded():
        import fakeredis.aioredis as fakeaioredis
        import fakeredis

        global _fake_server
        if _fake_server is None:
            _fake_server = fakeredis.FakeServer()
            log.info("Embedded mode: using in-process fakeredis (no Redis service)")
        return fakeaioredis.FakeRedis(
            server=_fake_server, decode_responses=decode_responses
        )

    import redis.asyncio as aioredis
    # Drop fakeredis-only kwargs that real redis wouldn't accept.
    return aioredis.from_url(settings.redis_url, decode_responses=decode_responses, **kwargs)
