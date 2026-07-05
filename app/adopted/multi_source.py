"""Multi-source ingest pipeline.

A single ingest API that accepts content from any of a fixed set of
source types, normalises it, and persists it through the regular memory
path:

    org_mode   — Emacs Org files
    markdown   — CommonMark / GFM
    plaintext  — Plain text
    pdf        — PDF (text extraction; OCR fallback for scanned pages)
    github     — GitHub issues, PRs, comments
    notion     — Notion page export
    image      — PNG / JPEG (OCR + visual description)
    speech     — WAV / MP3 (transcription)

A `Source` declares which types it supports.  The router in
`route_source()` picks the right extractor and returns a uniform
`IngestDocument`.  Persistence is the caller's job — typically you
chunk the document, embed each chunk, and call the regular
`save_memory` API for each.

This module is pure-Python: the actual extraction is pluggable.  We
ship:

- Pure-Python text extractors (org, markdown, plaintext) — always
  available, no external deps.
- A `PassthroughExtractor` for PDF / image / speech that returns the
  raw bytes — wire your favourite library (pypdf, pytesseract, whisper)
  in a subclass.

The pipeline does not prescribe chunking strategy.  Each extractor
returns a single `IngestDocument` and the caller splits it.
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence


class SourceType(str, Enum):
    """The supported ingest source types."""
    ORG_MODE  = "org"
    MARKDOWN  = "markdown"
    PLAINTEXT = "plaintext"
    PDF       = "pdf"
    GITHUB    = "github"
    NOTION    = "notion"
    IMAGE     = "image"
    SPEECH    = "speech"
    UNKNOWN   = "unknown"


SOURCE_TYPE_BY_EXTENSION: Dict[str, SourceType] = {
    ".org":     SourceType.ORG_MODE,
    ".md":      SourceType.MARKDOWN,
    ".txt":     SourceType.PLAINTEXT,
    ".pdf":     SourceType.PDF,
    ".png":     SourceType.IMAGE,
    ".jpg":     SourceType.IMAGE,
    ".jpeg":    SourceType.IMAGE,
    ".wav":     SourceType.SPEECH,
    ".mp3":     SourceType.SPEECH,
    ".m4a":     SourceType.SPEECH,
}


def detect_source_type(path: str) -> SourceType:
    """Detect the source type from a file path's extension."""
    if not path:
        return SourceType.UNKNOWN
    lower = path.lower()
    for ext, t in SOURCE_TYPE_BY_EXTENSION.items():
        if lower.endswith(ext):
            return t
    return SourceType.UNKNOWN


@dataclass
class IngestDocument:
    """The normalised output of any extractor."""
    text: str
    source_type: SourceType
    source_path: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def chunk(self, *, max_chars: int = 1500) -> List[str]:
        """A trivial chunker: split on blank lines, then on size.

        Real callers should use a smarter chunker (semantic, sliding,
        etc.).  This one is good enough for tests.
        """
        if len(self.text) <= max_chars:
            return [self.text]
        chunks: List[str] = []
        for block in self.text.split("\n\n"):
            if not block.strip():
                continue
            if len(block) <= max_chars:
                chunks.append(block.strip())
                continue
            # Block too long — split on sentence boundaries.
            current: List[str] = []
            current_len = 0
            for sentence in re.split(r"(?<=[.!?])\s+", block):
                if current_len + len(sentence) + 1 > max_chars and current:
                    chunks.append(" ".join(current).strip())
                    current = [sentence]
                    current_len = len(sentence)
                else:
                    current.append(sentence)
                    current_len += len(sentence) + 1
            if current:
                chunks.append(" ".join(current).strip())
        return chunks


# ---- Extractors --------------------------------------------------------

class Extractor(abc.ABC):
    """An extractor turns a source into a uniform `IngestDocument`."""

    supported: frozenset = frozenset()

    @abc.abstractmethod
    def can_extract(self, source: "Source") -> bool: ...

    @abc.abstractmethod
    def extract(self, source: "Source") -> IngestDocument: ...


# ---- Source -----------------------------------------------------------

@dataclass
class Source:
    """A source to ingest.  Either a path or a raw payload, plus a type."""
    path: Optional[str] = None
    payload: Optional[bytes] = None
    text: Optional[str] = None
    source_type: Optional[SourceType] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type is None and self.path is not None:
            self.source_type = detect_source_type(self.path)


# ---- Pure-Python text extractors --------------------------------------

class TextExtractor(Extractor):
    """Base class for extractors that return the source text as-is."""
    supported_kind: SourceType = SourceType.UNKNOWN

    def can_extract(self, source: Source) -> bool:
        return source.source_type == self.supported_kind

    def extract(self, source: Source) -> IngestDocument:
        if source.text is None:
            raise ValueError(f"{type(self).__name__} requires `source.text` to be set")
        return IngestDocument(
            text=source.text,
            source_type=self.supported_kind,
            source_path=source.path,
            title=source.title,
            metadata=dict(source.metadata),
        )


class PlaintextExtractor(TextExtractor):
    supported_kind = SourceType.PLAINTEXT


class MarkdownExtractor(TextExtractor):
    """Strips simple markdown formatting before returning the body."""
    supported_kind = SourceType.MARKDOWN

    def extract(self, source: Source) -> IngestDocument:
        raw = source.text or ""
        # Drop fenced code blocks — they are usually not memorable.
        raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)
        # Drop inline code spans.
        raw = re.sub(r"`[^`]+`", lambda m: m.group(0)[1:-1], raw)
        # Drop link syntax — keep the visible text.
        raw = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw)
        # Drop image syntax.
        raw = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", raw)
        # Drop header hashes.
        raw = re.sub(r"^#{1,6}\s+", "", raw, flags=re.MULTILINE)
        # Drop bold/italic markers.
        raw = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", raw)
        # Collapse whitespace.
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return IngestDocument(
            text=raw.strip(),
            source_type=self.supported_kind,
            source_path=source.path,
            title=source.title,
            metadata=dict(source.metadata),
        )


class OrgModeExtractor(TextExtractor):
    """Strips Org-mode syntax before returning the body."""
    supported_kind = SourceType.ORG_MODE

    def extract(self, source: Source) -> IngestDocument:
        raw = source.text or ""
        # Drop source-code blocks.
        raw = re.sub(r"#\+BEGIN_SRC.*?#\+END_SRC", "", raw, flags=re.DOTALL)
        # Drop export blocks.
        raw = re.sub(r"#\+BEGIN_[A-Z]+.*?#\+END_[A-Z]+", "", raw, flags=re.DOTALL)
        # Convert headings to plain text.
        raw = re.sub(r"^\*+\s+", "", raw, flags=re.MULTILINE)
        # Drop property drawers.
        raw = re.sub(r":PROPERTIES:.*?:END:", "", raw, flags=re.DOTALL)
        # Drop markup markers.
        raw = re.sub(r"[=/~]+", "", raw)
        # Drop links of the form [[url][label]] -> label.
        raw = re.sub(r"\[\[[^\]]+\]\[([^\]]+)\]\]", r"\1", raw)
        raw = re.sub(r"\[\[([^\]]+)\]\]", r"\1", raw)
        # Collapse whitespace.
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return IngestDocument(
            text=raw.strip(),
            source_type=self.supported_kind,
            source_path=source.path,
            title=source.title,
            metadata=dict(source.metadata),
        )


# ---- Binary placeholder extractors -----------------------------------

class PassthroughExtractor(Extractor):
    """A pass-through that returns the raw bytes as a single line of text.

    Useful when the real extractor is implemented elsewhere (pypdf,
    whisper, etc.) and you only want the source registered with the
    pipeline.  Wire your own by subclassing and overriding `extract`.
    """

    supported: frozenset = frozenset({SourceType.PDF, SourceType.IMAGE, SourceType.SPEECH, SourceType.GITHUB, SourceType.NOTION})

    def can_extract(self, source: Source) -> bool:
        return source.source_type in self.supported and source.payload is not None

    def extract(self, source: Source) -> IngestDocument:
        return IngestDocument(
            text=f"[unparsed binary: {source.source_type.value}, {len(source.payload or b'')} bytes]",
            source_type=source.source_type or SourceType.UNKNOWN,
            source_path=source.path,
            title=source.title,
            metadata={"unparsed": True, **source.metadata},
        )


# ---- Router -----------------------------------------------------------

DEFAULT_EXTRACTORS: List[Extractor] = [
    PlaintextExtractor(),
    MarkdownExtractor(),
    OrgModeExtractor(),
    PassthroughExtractor(),
]


def route_source(source: Source, extractors: Optional[Sequence[Extractor]] = None) -> IngestDocument:
    """Pick the first extractor that handles this source and run it."""
    extractors = extractors or DEFAULT_EXTRACTORS
    for ex in extractors:
        if ex.can_extract(source):
            return ex.extract(source)
    raise ValueError(f"no extractor for source type {source.source_type}")


__all__ = [
    "SourceType",
    "SOURCE_TYPE_BY_EXTENSION",
    "detect_source_type",
    "IngestDocument",
    "Source",
    "Extractor",
    "TextExtractor",
    "PlaintextExtractor",
    "MarkdownExtractor",
    "OrgModeExtractor",
    "PassthroughExtractor",
    "DEFAULT_EXTRACTORS",
    "route_source",
]
