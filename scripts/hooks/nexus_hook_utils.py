#!/usr/bin/env python3
"""Shared helpers for Nexus agent hooks."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any


NEXUS_URL = os.getenv("NEXUS_URL", "http://localhost:7777").rstrip("/")
NEXUS_TOKEN = os.getenv("NEXUS_SECRET", "")
AGENT_ID = os.getenv("NEXUS_AGENT_ID", "claude-code")
PROJECT_KEY = os.getenv("NEXUS_PROJECT_KEY") or Path.cwd().name
SESSION_FILE = Path(os.getenv(
    "NEXUS_SESSION_FILE",
    str(Path(tempfile.gettempdir()) / f"nexus-session-{AGENT_ID}-{PROJECT_KEY}.json"),
))


def nexus_request(method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 4) -> dict[str, Any] | list[Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if NEXUS_TOKEN:
        headers["Authorization"] = f"Bearer {NEXUS_TOKEN}"
    req = urllib.request.Request(f"{NEXUS_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def read_session_id() -> str | None:
    try:
        if not SESSION_FILE.exists():
            return None
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("session_id")
    except Exception:
        return None


def write_session_id(session_id: str) -> None:
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps({
            "session_id": session_id,
            "agent_id": AGENT_ID,
            "project_key": PROJECT_KEY,
        }), encoding="utf-8")
    except Exception:
        pass


def start_session(title: str | None = None, metadata: dict[str, Any] | None = None) -> str | None:
    existing = read_session_id()
    if existing:
        return existing
    try:
        data = nexus_request("POST", "/v1/sessions/start", {
            "agent_id": AGENT_ID,
            "project_key": PROJECT_KEY,
            "title": title or f"{AGENT_ID} session in {PROJECT_KEY}",
            "metadata": metadata or {},
        })
        sid = data.get("session_id") if isinstance(data, dict) else None
        if sid:
            write_session_id(sid)
        return sid
    except Exception:
        return None


def append_session(role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    if not content or not content.strip():
        return
    sid = read_session_id() or start_session(metadata={"auto_created": True})
    if not sid:
        return
    try:
        nexus_request("POST", f"/v1/sessions/{sid}/messages", {
            "role": role,
            "content": content[:200000],
            "metadata": metadata or {},
        })
    except Exception:
        pass


def end_session(summary: str | None = None, durable: bool = False, metadata: dict[str, Any] | None = None) -> None:
    sid = read_session_id()
    if not sid:
        return
    try:
        nexus_request("POST", f"/v1/sessions/{sid}/end", {
            "summary": summary,
            "durable": durable,
            "metadata": metadata or {},
        })
    except Exception:
        pass
