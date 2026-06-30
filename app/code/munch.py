"""MUNCH-style compact wire format for code-context responses.

Inspired by jcodemunch-mcp's MUNCH format.  Goal: shrink repeated
payloads (list of symbol cards, list of files, list of edges) to a
compact text encoding without losing structure.

Encoding rules:
  - Path prefixes are interned.  The first occurrence of `/home/kubuntux/synapse-memory/`
    becomes `@0` and `@0/app/mind/living_mind.py` represents the full path.
  - Repeated fields are tagged with a single-letter column header:
      `f` = file path (interned)
      `k` = kind
      `n` = name
      `l` = line (start..end)
      `s` = signature
      `d` = docstring
      `i` = id
    e.g. one symbol: `f@k0/app/mind/living_mind.py|k=function|n=think|l=142:306`
  - `~` separates records; `;` separates fields.

This is conservative — we only compress what's already in our responses
and add a top-level `format` key so the receiver can decode.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence

COLUMN_TAGS: Dict[str, str] = {
    "id": "i",
    "name": "n",
    "qualified_name": "q",
    "kind": "k",
    "path": "f",
    "start_line": "s",
    "end_line": "e",
    "signature": "g",
    "docstring": "d",
    "language": "l",
    "complexity": "c",
    "weight": "w",
    "confidence": "o",
}


def _intern_path_prefixes(paths: Iterable[str]) -> List[str]:
    """Find common prefixes and assign short integer handles to them.

    Returns a list of (handle, prefix) pairs in order of decreasing
    frequency.  Caller is responsible for replacing prefixes in records.
    """
    counter: Dict[str, int] = {}
    for p in paths:
        # Split into path parts; look at all prefixes.
        parts = p.split("/")
        for i in range(1, len(parts)):
            prefix = "/".join(parts[:i]) + "/"
            counter[prefix] = counter.get(prefix, 0) + 1
    # Sort by count desc, then prefix length desc (longer first)
    sorted_prefixes = sorted(counter.items(), key=lambda x: (-x[1], -len(x[0])))
    # Only keep prefixes that appear more than once
    return [(f"@{i}", prefix) for i, (prefix, count) in enumerate(sorted_prefixes) if count > 1]


def _shorten_path(path: str, prefixes: List[tuple]) -> str:
    for handle, prefix in prefixes:
        if path.startswith(prefix):
            return handle + path[len(prefix):]
    return path


def _format_row(record: Dict[str, Any], columns: Sequence[str], prefixes: List[tuple]) -> str:
    """Format a single record using the given column set."""
    parts = []
    for col in columns:
        if col == "path":
            v = _shorten_path(str(record.get(col, "")), prefixes)
        else:
            v = str(record.get(col, ""))
        parts.append(v)
    return ";".join(parts)


def encode_records(
    records: Sequence[Dict[str, Any]],
    columns: Sequence[str],
    *,
    use_path_intern: bool = True,
) -> str:
    """Encode a list of dict records as a compact multi-line string.

    Args:
        records: list of dict-like records (must each have the same keys
            as `columns`).
        columns: ordered list of column names to include.
        use_path_intern: if True, intern common path prefixes.

    Returns:
        A compact string with a header line and one record per line.
        Header format: `MUNCH|cols|k=f;n=q;...|prefixes=@0=/home/...;@1=/usr/...`
        Body format:    one record per line, fields `;`-separated
    """
    if not records:
        return f"MUNCH|cols|{'|'.join(COLUMN_TAGS.get(c, c[:1]) for c in columns)}|prefixes=|body="

    prefixes: List[tuple] = []
    if use_path_intern and "path" in columns:
        prefixes = _intern_path_prefixes(r.get("path", "") for r in records)
    head = "|".join(COLUMN_TAGS.get(c, c[:1]) for c in columns)
    pref_str = ";".join(f"{h}={p}" for h, p in prefixes)
    body = "\n".join(_format_row(r, columns, prefixes) for r in records)
    return f"MUNCH|cols={head}|prefixes={pref_str}|body=\n{body}"
    body = "\n".join(_format_row(r, columns, prefixes) for r in records)
    return f"MUNCH|cols={head}|prefixes={pref_str}|body=\n{body}"


def decode_records(blob: str) -> List[Dict[str, str]]:
    """Decode a MUNCH blob back into a list of dicts.

    Inverse of `encode_records`.  Returns the records as flat string
    dicts (no type coercion)."""
    lines = blob.split("\n", 1)
    if not lines or not lines[0].startswith("MUNCH|"):
        raise ValueError("not a MUNCH blob")
    header, body = lines[0], lines[1] if len(lines) > 1 else ""
    # Header format: "MUNCH|cols=<col1>|<col2>|...|prefixes=<p1>;<p2>|body="
    # The col names use single-letter tags.  Parse the cols section by
    # finding the 'cols=' prefix and stopping at the next known section.
    cols_str = ""
    prefixes_str = ""
    for part in header.split("|"):
        if part.startswith("cols="):
            cols_str = part[len("cols="):]
        elif part.startswith("prefixes="):
            prefixes_str = part[len("prefixes="):]
    cols = cols_str.split("|") if cols_str else []
    col_names = []
    for c in cols:
        # reverse-lookup
        for name, tag in COLUMN_TAGS.items():
            if tag == c:
                col_names.append(name)
                break
        else:
            col_names.append(c)
    pref_str = parts[2].split("=", 1)[1] if "=" in parts[2] else ""
    prefixes = {}
    for p in pref_str.split(";") if pref_str else []:
        if "=" in p:
            h, path = p.split("=", 1)
            prefixes[h] = path
    out = []
    for line in body.strip().split("\n"):
        if not line:
            continue
        record = {}
        for col, val in zip(col_names, line.split(";")):
            if col == "path" and val.startswith("@"):
                for handle, prefix in prefixes.items():
                    if val.startswith(handle):
                        val = prefix + val[len(handle):]
                        break
            record[col] = val
        out.append(record)
    return out


# ── Response serializers for code-context endpoints ───────────────────

def serialize_code_search(
    data: Dict[str, Any],
    fmt: str = "auto",
) -> Any:
    """Convert a code-context API response to the requested format.

    fmt: 'auto' (default JSON unless savings >= 15%), 'compact' (always
    MUNCH), or 'json' (always verbose JSON).
    """
    if fmt == "json":
        return data
    if "symbols" not in data or not data["symbols"]:
        return data  # nothing to compress
    cols = ["qualified_name", "kind", "path", "start_line", "end_line", "docstring"]
    full = json.dumps(data, default=str)
    blob = encode_records(data["symbols"], cols)
    if fmt == "compact" or (fmt == "auto" and len(blob) < len(full) * 0.85):
        return {
            "format": "munch",
            "compression_ratio": round(len(blob) / max(len(full), 1), 3),
            "original_bytes": len(full),
            "compact_bytes": len(blob),
            "blob": blob,
            "count": data.get("count", len(data["symbols"])),
        }
    return data


def serialize_wiki_index(data: Dict[str, Any], fmt: str = "auto") -> Any:
    if fmt == "json":
        return data
    if "articles" not in data or not data["articles"]:
        return data
    cols = ["title", "slug", "section", "tokens"]
    full = json.dumps(data, default=str)
    blob = encode_records(data["articles"], cols)
    if fmt == "compact" or (fmt == "auto" and len(blob) < len(full) * 0.85):
        return {
            "format": "munch",
            "compression_ratio": round(len(blob) / max(len(full), 1), 3),
            "original_bytes": len(full),
            "compact_bytes": len(blob),
            "blob": blob,
            "count": data.get("count", 0),
        }
    return data


def serialize_blast(data: Dict[str, Any], fmt: str = "auto") -> Any:
    if fmt == "json":
        return data
    if "symbols" not in data or not data["symbols"]:
        return data
    cols = ["depth", "qualified_name", "kind"]
    rows = [{"depth": s["depth"], "qualified_name": s["symbol"]["qualified_name"], "kind": s["symbol"]["kind"]} for s in data["symbols"]]
    full = json.dumps(data, default=str)
    blob = encode_records(rows, cols)
    if fmt == "compact" or (fmt == "auto" and len(blob) < len(full) * 0.85):
        return {
            "format": "munch",
            "compression_ratio": round(len(blob) / max(len(full), 1), 3),
            "original_bytes": len(full),
            "compact_bytes": len(blob),
            "blob": blob,
            "total_affected": data.get("total_affected", 0),
            "by_depth": data.get("by_depth", {}),
        }
    return data


__all__ = [
    "encode_records", "decode_records",
    "serialize_code_search", "serialize_wiki_index", "serialize_blast",
    "COLUMN_TAGS",
]
