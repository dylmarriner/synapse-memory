"""File injection adapter — writes context into config files agents read at startup.

Supports CLAUDE.md (delimited block), plain instruction files, and JSON config
files that have a system_prompt or instructions field.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from app.push.adapters.base import PushAdapter

log = logging.getLogger("nexus.push.file_inject")

_MARKER_START = "<!-- NEXUS_CONTEXT_START -->"
_MARKER_END = "<!-- NEXUS_CONTEXT_END -->"


class FileInjectAdapter(PushAdapter):
    """Writes a Nexus context block into a target file."""

    adapter_type = "file_inject"

    def __init__(self, path: str, mode: str = "markdown_block"):
        """
        mode:
          markdown_block  — inject between NEXUS_CONTEXT_START/END markers (CLAUDE.md style)
          append_section  — append/replace a ## Nexus Context section
          json_field      — update a specific JSON field (field specified as config["json_field"])
        """
        self.path = Path(path).expanduser()
        self.mode = mode

    async def push(self, agent_id: str, snapshot: str, meta: dict[str, Any]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            if self.mode == "markdown_block":
                return self._inject_markdown_block(snapshot)
            elif self.mode == "append_section":
                return self._append_section(snapshot)
            elif self.mode == "json_field":
                return self._inject_json_field(snapshot, meta.get("json_field", "system_prompt"))
            else:
                log.warning("Unknown file_inject mode: %s", self.mode)
                return False
        except Exception as e:
            log.error("file_inject failed for %s: %s", self.path, e)
            return False

    def _inject_markdown_block(self, snapshot: str) -> bool:
        block = f"{_MARKER_START}\n{snapshot}\n{_MARKER_END}\n"
        if self.path.exists():
            content = self.path.read_text()
            if _MARKER_START in content:
                # Replace existing block
                content = re.sub(
                    rf"{re.escape(_MARKER_START)}.*?{re.escape(_MARKER_END)}\n?",
                    block,
                    content,
                    flags=re.DOTALL,
                )
            else:
                content = block + "\n" + content
        else:
            content = block
        self.path.write_text(content)
        log.info("Injected context block into %s", self.path)
        return True

    def _append_section(self, snapshot: str) -> bool:
        section_header = "## Nexus Active Context"
        section = f"\n{section_header}\n{snapshot}\n"
        if self.path.exists():
            content = self.path.read_text()
            if section_header in content:
                content = re.sub(
                    rf"\n{re.escape(section_header)}\n.*?(?=\n## |\Z)",
                    section,
                    content,
                    flags=re.DOTALL,
                )
            else:
                content += section
        else:
            content = section
        self.path.write_text(content)
        return True

    def _inject_json_field(self, snapshot: str, field: str) -> bool:
        if self.path.exists():
            data = json.loads(self.path.read_text())
        else:
            data = {}
        data[field] = snapshot
        self.path.write_text(json.dumps(data, indent=2))
        return True
