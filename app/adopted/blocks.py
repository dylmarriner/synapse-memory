"""In-context named memory blocks.

A `Block` is a labelled section of the agent's core (in-context) memory,
like a small file the agent can read and edit on the fly.  Each block has:

- `label`    — the slot name (e.g. "persona", "human", "project_overview")
- `value`    — the actual text content
- `limit`    — character budget; the agent can be warned when near full
- `description` — what this slot is for, shown to the agent
- `read_only` — whether the agent is allowed to edit the value
- `hidden`   — visible in the system prompt, or only in management UI

Blocks are rendered together into a `<memory_blocks>` XML section that the
agent sees in its system prompt.  The agent edits blocks with two
operations:

- `core_memory_append(label, content)`  — append to the block
- `core_memory_replace(label, old, new)` — replace exact substring

The total size of all blocks is the agent's in-context "working memory".
A separate archival store (the rest of Nexus) holds everything that does
not fit in core.

Two pre-defined blocks:

- `persona` — the agent's self-description and operating instructions
- `human`   — what the agent knows about the human it is talking to

These are the defaults a new agent gets.  More blocks can be added.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

CORE_MEMORY_BLOCK_CHAR_LIMIT: int = 2000
CORE_MEMORY_LINE_NUMBER_WARNING: str = (
    "Lines are 1-indexed.  Quote a line by its number, not its text, when "
    "editing — text matching is fragile once the block has been edited."
)


@dataclass
class Block:
    """A named slot of the agent's in-context memory."""
    label: str
    value: str = ""
    description: str = ""
    limit: int = CORE_MEMORY_BLOCK_CHAR_LIMIT
    read_only: bool = False
    hidden: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("Block.label is required")
        if self.limit < len(self.value):
            raise ValueError(
                f"Block {self.label!r}: limit {self.limit} < current length {len(self.value)}"
            )

    @property
    def chars_current(self) -> int:
        return len(self.value)

    @property
    def chars_remaining(self) -> int:
        return max(0, self.limit - self.chars_current)

    @property
    def is_full(self) -> bool:
        return self.chars_current >= self.limit

    @property
    def fill_ratio(self) -> float:
        if self.limit <= 0:
            return 0.0
        return min(1.0, self.chars_current / self.limit)

    def append(self, content: str) -> "Block":
        """Append content to the block, respecting the limit."""
        if self.read_only:
            raise PermissionError(f"Block {self.label!r} is read-only")
        if not content:
            return self
        separator = "" if (not self.value or self.value.endswith("\n")) else "\n"
        candidate = self.value + separator + content
        if len(candidate) > self.limit:
            raise OverflowError(
                f"Block {self.label!r}: append would exceed limit "
                f"({len(candidate)} > {self.limit})"
            )
        return replace(self, value=candidate)

    def replace(self, old: str, new: str) -> "Block":
        """Replace an exact substring, respecting the limit and read-only."""
        if self.read_only:
            raise PermissionError(f"Block {self.label!r} is read-only")
        if old not in self.value:
            raise ValueError(
                f"Block {self.label!r}: old substring not found (length {len(old)})"
            )
        candidate = self.value.replace(old, new)
        if len(candidate) > self.limit:
            raise OverflowError(
                f"Block {self.label!r}: replace would exceed limit "
                f"({len(candidate)} > {self.limit})"
            )
        return replace(self, value=candidate)


@dataclass
class Persona(Block):
    """Default block: the agent's self-description."""
    label: str = "persona"
    description: str = "Persona block. Update this whenever the agent's role or self-description changes."


@dataclass
class Human(Block):
    """Default block: what the agent knows about the human."""
    label: str = "human"
    description: str = "Human block. Update this whenever the agent learns something durable about the user."


DEFAULT_BLOCKS: List[Block] = [
    Persona(value="I am a Nexus memory agent."),
    Human(value=""),
]


def new_default_blockstore() -> Dict[str, Block]:
    """Return a fresh block store seeded with persona + human blocks."""
    return {b.label: b for b in DEFAULT_BLOCKS}


# ---- Rendering --------------------------------------------------------------

def _display_label(label: str) -> str:
    """Sanitize a block label for use as an XML tag name."""
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in label)


def render_memory_blocks(
    blocks: List[Block],
    *,
    line_numbered: bool = False,
) -> str:
    """Render a list of blocks into the `<memory_blocks>...</memory_blocks>`
    XML section the agent sees in its system prompt.

    Hidden blocks and empty blocks are skipped.
    """
    visible = [b for b in blocks if not b.hidden and b.value]
    if not visible:
        return ""
    lines: List[str] = [
        "<memory_blocks>",
        "The following memory blocks are currently engaged in your core memory unit:",
        "",
    ]
    for idx, block in enumerate(visible):
        tag = _display_label(block.label)
        lines.append(f"<{tag}>")
        if block.description:
            lines.append("<description>")
            lines.append(block.description)
            lines.append("</description>")
        meta = []
        if block.read_only:
            meta.append("- read_only=true")
        meta.append(f"- chars_current={block.chars_current}")
        meta.append(f"- chars_limit={block.limit}")
        lines.append("<metadata>")
        lines.extend(meta)
        lines.append("</metadata>")
        if line_numbered:
            lines.append(f"<warning>{CORE_MEMORY_LINE_NUMBER_WARNING}</warning>")
            lines.append("<value>")
            if block.value:
                for i, line in enumerate(block.value.split("\n"), start=1):
                    lines.append(f"{i}\u2192 {line}")
            lines.append("</value>")
        else:
            lines.append("<value>")
            lines.append(block.value)
            lines.append("</value>")
        lines.append(f"</{tag}>")
        if idx != len(visible) - 1:
            lines.append("")
    lines.append("</memory_blocks>")
    return "\n".join(lines)


__all__ = [
    "Block",
    "Persona",
    "Human",
    "DEFAULT_BLOCKS",
    "CORE_MEMORY_BLOCK_CHAR_LIMIT",
    "CORE_MEMORY_LINE_NUMBER_WARNING",
    "new_default_blockstore",
    "render_memory_blocks",
]
