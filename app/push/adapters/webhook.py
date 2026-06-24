"""Webhook adapter — HTTP POST to a registered callback URL.

Used by agents that expose a callback endpoint (Paperclip plugin host,
custom agent runners, n8n/Flowise workflows, etc).
"""

import logging
from typing import Any

import httpx

from app.push.adapters.base import PushAdapter

log = logging.getLogger("nexus.push.webhook")


class WebhookAdapter(PushAdapter):
    adapter_type = "webhook"

    def __init__(self, url: str, secret: str = "", timeout: float = 5.0):
        self.url = url
        self.secret = secret
        self.timeout = timeout

    async def push(self, agent_id: str, snapshot: str, meta: dict[str, Any]) -> bool:
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Nexus-Secret"] = self.secret
        payload = {
            "agent_id": agent_id,
            "snapshot": snapshot,
            "event": meta.get("event", "memory_update"),
            "timestamp": meta.get("timestamp"),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self.url, json=payload, headers=headers)
                if r.status_code < 300:
                    log.info("Webhook push OK: %s → %s", agent_id, self.url)
                    return True
                log.warning("Webhook push non-2xx %s for %s", r.status_code, self.url)
                return False
        except Exception as e:
            log.error("Webhook push failed for %s: %s", self.url, e)
            return False
