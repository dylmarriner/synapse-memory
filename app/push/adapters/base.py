"""Base class for all Nexus push adapters."""

from abc import ABC, abstractmethod
from typing import Any


class PushAdapter(ABC):
    """Delivers a context snapshot to a specific agent via its native mechanism."""

    @abstractmethod
    async def push(self, agent_id: str, snapshot: str, meta: dict[str, Any]) -> bool:
        """Push snapshot to agent. Returns True on success."""
        ...

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        ...
