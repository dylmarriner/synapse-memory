"""Tests for the Hermes Living Mind plugin."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

HERMES_PLUGIN = Path(__file__).resolve().parents[2] / "integrations" / "plugins" / "hermes-mind"


def _load_hermes_plugin(monkeypatch):
    """Import the hermes plugin module fresh, with controlled env."""
    # Set env before import
    monkeypatch.setenv("NEXUS_URL", "http://localhost:7777")
    monkeypatch.setenv("NEXUS_SECRET", "test-secret")
    monkeypatch.setenv("MIND_ID", "default")
    monkeypatch.setenv("AGENT_ID", "hermes")
    # Drop cached imports
    for mod in list(sys.modules):
        if "hermes_mind" in mod or "hermes-mind" in mod:
            del sys.modules[mod]
    sys.path.insert(0, str(HERMES_PLUGIN))
    import importlib
    # The plugin module is named __init__.py — import the package
    plugin_pkg = importlib.import_module("__init__")
    return plugin_pkg


def _mock_urlopen_factory(responses: dict):
    def factory(req, timeout=5):
        url = req.full_url
        for substring, body in responses.items():
            if substring in url:
                mock = MagicMock()
                mock.__enter__ = lambda self: mock
                mock.__exit__ = lambda *args: None
                mock.read.return_value = json.dumps(body).encode()
                return mock
        mock = MagicMock()
        mock.__enter__ = lambda self: mock
        mock.__exit__ = lambda *args: None
        mock.read.return_value = b"{}"
        return mock
    return factory


def test_hermes_session_start_injects_briefing(monkeypatch):
    responses = {
        "identity": {
            "mind_id": "default",
            "description": "I am the test mind.",
        },
        "think": {
            "proactive_context": [
                {"type": "unfinished_promise", "content": "refactor auth", "relevance": 0.9}
            ],
        },
        "opinions": {
            "opinions": {
                "auth_module": {"stance": "negative", "strength": 0.8, "evidence_count": 5}
            }
        },
    }
    plugin = _load_hermes_plugin(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        result = plugin.on_session_start({})
    assert result is not None
    assert "system_prompt_addition" in result
    assert "I am the test mind" in result["system_prompt_addition"]
    assert "refactor auth" in result["system_prompt_addition"]
    assert "negative" in result["system_prompt_addition"]


def test_hermes_session_start_silent_when_no_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_SECRET", "")
    plugin = _load_hermes_plugin(monkeypatch)
    result = plugin.on_session_start({})
    assert result is None


def test_hermes_session_start_handles_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise URLError("connection refused")
    plugin = _load_hermes_plugin(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=boom):
        result = plugin.on_session_start({})
    assert result is None


def test_hermes_prompt_submit_returns_context(monkeypatch):
    responses = {
        "think": {
            "proactive_context": [
                {"type": "recent_work", "content": "test item", "relevance": 0.8}
            ],
        }
    }
    plugin = _load_hermes_plugin(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        result = plugin.on_prompt_submit("What about the auth module?", {})
    assert result is not None
    assert "context_addition" in result
    assert "test item" in result["context_addition"]


def test_hermes_prompt_submit_silent_when_no_proactive(monkeypatch):
    responses = {"think": {"proactive_context": []}}
    plugin = _load_hermes_plugin(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        result = plugin.on_prompt_submit("hello", {})
    assert result is None


def test_hermes_session_end_saves_summary(monkeypatch):
    captured = {}
    def capture_urlopen(req, timeout=5):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        mock = MagicMock()
        mock.__enter__ = lambda self: mock
        mock.__exit__ = lambda *args: None
        mock.read.return_value = json.dumps({"id": "summary-1"}).encode()
        return mock
    plugin = _load_hermes_plugin(monkeypatch)
    with patch("urllib.request.urlopen", side_effect=capture_urlopen):
        plugin.on_session_end("Worked on auth module", {})
    assert "memory/save" in captured["url"]
    assert "session_summary" in captured["data"]["tags"]


def test_hermes_plugin_manifest_lists_hooks():
    import yaml
    p = HERMES_PLUGIN / "plugin.yaml"
    assert p.exists(), "plugin.yaml missing"
    manifest = yaml.safe_load(p.read_text())
    assert "hooks" in manifest
    events = {h["event"] for h in manifest["hooks"]}
    assert "session_start" in events
    assert "prompt_submit" in events
    assert "session_end" in events
