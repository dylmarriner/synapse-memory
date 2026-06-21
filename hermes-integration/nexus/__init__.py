"""Nexus memory provider for Hermes — unified 4-way recall with lessons and summaries."""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Keywords that indicate new information worth remembering
_INFORMATION_KEYWORDS = [
    "i like", "i prefer", "i use", "remember that", "note:", "important",
    "my favorite", "i always", "i never", "don't forget", "keep in mind",
    "i usually", "i typically", "i want", "i need", "make sure"
]

# Tool schemas exposed to the LLM
_TOOLS = [
    {
        "name": "nexus_recall",
        "description": (
            "Search Nexus long-term memory using 4-way parallel recall: semantic vector, "
            "lexical BM25, entity graph, and temporal recency — fused with Reciprocal Rank Fusion. "
            "Use to retrieve past context, user preferences, facts, and lessons."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "default": 8},
                "memory_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter: world, experience, observation, preference, lesson",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "nexus_save",
        "description": (
            "Save something to Nexus long-term memory. "
            "Use for: important facts (world), events that happened (experience), "
            "insights (observation), user preferences (preference)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "memory_type": {
                    "type": "string",
                    "enum": ["world", "experience", "observation", "preference", "lesson"],
                },
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
            },
            "required": ["content"],
        },
    },
    {
        "name": "nexus_save_lesson",
        "description": (
            "Save a lesson, correction, or mistake to Nexus. "
            "WHEN TO USE: after making an error, receiving a correction, or learning something "
            "that prevents future mistakes. High importance (0.9), never decayed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The lesson (e.g. 'I was wrong about X — correct answer is Y')"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "nexus_reflect",
        "description": (
            "Ask Nexus to synthesize all stored memories on a topic using LLM reasoning. "
            "Returns a structured knowledge synthesis. More thorough than nexus_recall."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "depth": {"type": "string", "enum": ["low", "mid", "high"], "default": "mid"},
            },
            "required": ["query"],
        },
    },
]


def _contains_informational_content(content: str) -> bool:
    """Check if content contains keywords indicating new information worth remembering."""
    content_lower = content.lower()
    return any(keyword in content_lower for keyword in _INFORMATION_KEYWORDS)


class NexusMemoryProvider:
    """Nexus unified memory provider with optimized token usage."""

    def __init__(self):
        self._agent_id: str = "hermes"
        self._enabled: bool = True
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._context_cache: Optional[dict] = None
        self._char_limit: int = 2200

    @property
    def name(self) -> str:
        return "nexus"

    def is_available(self) -> bool:
        from plugins.memory.nexus.client import health
        try:
            return health()
        except Exception:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        from plugins.memory.nexus import client as nc
        self._agent_id = kwargs.get("agent_identity", "hermes")
        self._char_limit = kwargs.get("memory_char_limit", 2200)

        # Warm up: load agent context in background
        def _warm():
            try:
                ctx = nc.agent_context(self._agent_id, tokens=1500)
                self._context_cache = ctx
                # Update agent activity for registry
                nc.update_agent_activity(self._agent_id)
            except Exception as e:
                logger.debug("Nexus warmup failed: %s", e)

        t = threading.Thread(target=_warm, daemon=True)
        t.start()
        logger.info("Nexus memory provider initialized for agent '%s'", self._agent_id)

    def system_prompt_block(self) -> str:
        """Optimized context injection: only summary + top 3 conclusions (saves 400-800 tokens)."""
        if not self._context_cache:
            return ""
        ctx = self._context_cache
        lines = ["## Nexus Memory Context"]

        # Always include summary
        summary = ctx.get("summary")
        if summary:
            lines.append(f"\n**Rolling Summary:**\n{summary}")

        # Only top 3 most important conclusions (was up to 8)
        conclusions = ctx.get("conclusions", [])
        if conclusions:
            lines.append("\n**Key Conclusions:**")
            for c in conclusions[:3]:  # Optimized from [:8] to [:3]
                lines.append(f"  - {c}")

        block = "\n".join(lines)
        return block[:self._char_limit] if block.strip() != "## Nexus Memory Context" else ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""

        if result:
            return result

        # Synchronous fallback (fast path — vector+lexical only)
        from plugins.memory.nexus import client as nc
        try:
            results = nc.recall(query, agent_id=self._agent_id, limit=5,
                                modes=["vector", "lexical"])
            if not results:
                return ""
            lines = ["[Nexus recall:]"]
            for m in results:
                mtype = m.get("memory_type", "?")
                score = m.get("score", 0)
                content = m.get("content", "")[:250]
                lines.append(f"  [{mtype}|{score:.2f}] {content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def sync_turn(self, user_content: str, assistant_content: str,
                  *, session_id: str = "") -> None:
        """Conditional save: only save if content contains informational keywords."""
        if not user_content.strip():
            return

        # Skip if content is too short
        if len(user_content.strip()) < 20:
            return

        # Conditional save: only if contains informational keywords
        if not _contains_informational_content(user_content):
            logger.debug("Nexus: skipped save (no informational keywords)")
            return

        def _save():
            from plugins.memory.nexus import client as nc
            try:
                # Save user message as experience
                nc.save_memory(
                    content=user_content[:800],
                    agent_id=self._agent_id,
                    memory_type="experience",
                    importance=0.5,
                )
                logger.debug("Nexus: saved memory (informational content detected)")
            except Exception as e:
                logger.debug("Nexus sync_turn save failed: %s", e)

        threading.Thread(target=_save, daemon=True).start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return _TOOLS

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        from plugins.memory.nexus import client as nc

        if tool_name == "nexus_recall":
            results = nc.recall(
                query=args.get("query", ""),
                agent_id=self._agent_id,
                limit=args.get("limit", 8),
            )
            if not results:
                return json.dumps({"results": [], "message": "No memories found."})
            formatted = [
                {
                    "type": m.get("memory_type"),
                    "score": round(m.get("score", 0), 3),
                    "content": m.get("content", ""),
                }
                for m in results
            ]
            return json.dumps({"results": formatted, "total": len(formatted)})

        elif tool_name == "nexus_save":
            r = nc.save_memory(
                content=args.get("content", ""),
                agent_id=self._agent_id,
                memory_type=args.get("memory_type"),
                importance=args.get("importance", 0.6),
            )
            return json.dumps(r or {"error": "Save failed"})

        elif tool_name == "nexus_save_lesson":
            r = nc.save_lesson(
                content=args.get("content", ""),
                agent_id=self._agent_id,
            )
            return json.dumps(r or {"error": "Save failed"})

        elif tool_name == "nexus_reflect":
            reflection = nc.reflect(
                query=args.get("query", ""),
                agent_id=self._agent_id,
                depth=args.get("depth", "mid"),
            )
            return json.dumps({"reflection": reflection})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def on_session_end(self, messages: list) -> None:
        """Trigger agent representation rebuild at session end."""
        def _rebuild():
            try:
                import urllib.request
                from plugins.memory.nexus.client import _headers, NEXUS_URL
                req = urllib.request.Request(
                    f"{NEXUS_URL}/v1/browse/agents/{self._agent_id}/represent",
                    data=b"",
                    headers=_headers(),
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=15)
                logger.info("Nexus: representation rebuilt for '%s'", self._agent_id)
            except Exception as e:
                logger.debug("Nexus represent failed: %s", e)

        threading.Thread(target=_rebuild, daemon=True).start()

    def shutdown(self) -> None:
        logger.info("Nexus provider shutdown")


PROVIDER = NexusMemoryProvider