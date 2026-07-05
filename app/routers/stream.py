"""SSE live feed — streams new memory events to dashboard clients."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import StreamingResponse

from app import broadcaster

log = logging.getLogger("nexus.stream")
router = APIRouter()


@router.get("/stream")
async def memory_stream(request: Request, Authorization: Optional[str] = Query(default=None)):
    """SSE endpoint — connect to receive live memory events.
    Accepts auth via Bearer header or ?Authorization=Bearer+... query param (for EventSource).
    """
    from app.config import settings
    from app.main import _verify_dashboard_token
    secret = settings.nexus_secret
    if secret and not settings.nexus_disable_auth:
        auth = request.headers.get("Authorization", "") or Authorization or ""
        token = auth.removeprefix("Bearer ").strip()
        if token != secret and not _verify_dashboard_token(token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    q = await broadcaster.subscribe()

    async def event_generator():
        try:
            # Send connected ping
            yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20.0)
                    payload = json.dumps(event["data"])
                    yield f"event: {event['type']}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
