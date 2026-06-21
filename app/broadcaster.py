"""In-memory SSE broadcaster — push new memory events to all connected dashboard clients."""

import asyncio
from typing import List, Dict, Any

_queues: List[asyncio.Queue] = []


async def broadcast(event_type: str, data: Dict[str, Any]):
    """Push an event to all connected SSE clients."""
    for q in _queues[:]:
        try:
            q.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            pass


async def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _queues.append(q)
    return q


async def unsubscribe(q: asyncio.Queue):
    try:
        _queues.remove(q)
    except ValueError:
        pass
