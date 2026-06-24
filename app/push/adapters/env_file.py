"""Env file adapter — writes context into a .env style file agents bootstrap from.

Used by OpenHands, SWE-agent, and other CLI agents that read a nexus.env
at startup and inject it as environment variables or a system prompt.
"""

import logging
from pathlib import Path
from typing import Any

from app.push.adapters.base import PushAdapter

log = logging.getLogger("nexus.push.env_file")


class EnvFileAdapter(PushAdapter):
    adapter_type = "env_file"

    def __init__(self, path: str, var_name: str = "NEXUS_CONTEXT"):
        self.path = Path(path).expanduser()
        self.var_name = var_name

    async def push(self, agent_id: str, snapshot: str, meta: dict[str, Any]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Escape newlines for env var format
            escaped = snapshot.replace("\n", "\\n").replace('"', '\\"')
            lines = []
            if self.path.exists():
                for line in self.path.read_text().splitlines():
                    if not line.startswith(f"{self.var_name}="):
                        lines.append(line)
            lines.append(f'{self.var_name}="{escaped}"')
            self.path.write_text("\n".join(lines) + "\n")
            log.info("Env file updated: %s", self.path)
            return True
        except Exception as e:
            log.error("env_file push failed for %s: %s", self.path, e)
            return False
