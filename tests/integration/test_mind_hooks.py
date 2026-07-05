"""Tests for the Living Mind agent hooks.

The hooks are simple scripts that POST to the Nexus REST API.
We test them by importing their `main()` function and mocking
the HTTP layer in-process.  The hooks are designed to be
import-safe (they read env at call time, not import time).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / "integrations" / "plugins" / "claude-code-mind" / "hooks"


def _load_hook(name: str):
    """Import a hook script as a module so we can call main() in-process."""
    script = HOOKS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"hook_{name}", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Set sane env for all tests
@pytest.fixture(autouse=True)
def hook_env(monkeypatch):
    monkeypatch.setenv("NEXUS_URL", "http://localhost:7777")
    monkeypatch.setenv("NEXUS_SECRET", "test-secret")
    monkeypatch.setenv("MIND_ID", "default")
    monkeypatch.setenv("AGENT_ID", "claude-code")


def _mock_urlopen_factory(responses: dict):
    """Build a mock urlopen that returns different responses by URL."""
    def factory(req, timeout=5):
        url = req.full_url
        for substring, body in responses.items():
            if substring in url:
                mock = MagicMock()
                mock.__enter__ = lambda self: mock
                mock.__exit__ = lambda *args: None
                mock.read.return_value = json.dumps(body).encode()
                return mock
        # Default: empty
        mock = MagicMock()
        mock.__enter__ = lambda self: mock
        mock.__exit__ = lambda *args: None
        mock.read.return_value = b"{}"
        return mock
    return factory


# ---- session_start hook --------------------------------------------------

def test_session_start_outputs_briefing(monkeypatch):
    responses = {
        "identity": {
            "mind_id": "default",
            "description": "I am the test mind. I have core trait: reasoning.",
            "identity": {"core_traits": ["reasoning"]},
        },
        "think": {
            "answer": "Test answer",
            "proactive_context": [
                {"type": "unfinished_promise", "content": "test promise", "relevance": 0.9}
            ],
        },
        "opinions": {
            "opinions": {
                "auth_module": {"stance": "negative", "strength": 0.8, "evidence_count": 5}
            }
        },
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        with patch("sys.stdout") as mock_stdout:
            hook = _load_hook("session_start")
            rc = hook.main()
        assert rc == 0
        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "I am the test mind" in output
        assert "test promise" in output
        assert "negative" in output


def test_session_start_fails_silently_without_secret(monkeypatch):
    monkeypatch.setenv("NEXUS_SECRET", "")
    with patch("sys.stdout") as mock_stdout:
        hook = _load_hook("session_start")
        rc = hook.main()
    assert rc == 0
    output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
    assert output == ""


def test_session_start_fails_silently_on_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=boom):
        with patch("sys.stdout") as mock_stdout:
            hook = _load_hook("session_start")
            rc = hook.main()
    assert rc == 0


# ---- prompt_submit hook -------------------------------------------------

def test_prompt_submit_includes_proactive(monkeypatch):
    responses = {
        "think": {
            "answer": "Test",
            "proactive_context": [
                {"type": "recent_work", "content": "test item", "relevance": 0.8}
            ],
        }
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        with patch("sys.stdin", new=type("S", (), {"read": lambda self: json.dumps({"prompt": "What about the auth module?"})})()):
            with patch("sys.stdout") as mock_stdout:
                hook = _load_hook("prompt_submit")
                rc = hook.main()
        assert rc == 0
        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "test item" in output


def test_prompt_submit_handles_empty_stdin(monkeypatch):
    with patch("sys.stdin", new=type("S", (), {"read": lambda self: ""})()):
        with patch("sys.stdout") as mock_stdout:
            hook = _load_hook("prompt_submit")
            rc = hook.main()
    assert rc == 0
    output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
    assert output == ""


def test_prompt_submit_handles_invalid_json(monkeypatch):
    with patch("sys.stdin", new=type("S", (), {"read": lambda self: "not json"})()):
        with patch("sys.stdout") as mock_stdout:
            hook = _load_hook("prompt_submit")
            rc = hook.main()
    assert rc == 0
    output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
    assert output == ""


def test_prompt_submit_asks_back_when_mind_does(monkeypatch):
    responses = {
        "think": {
            "answer": None,
            "clarifying_question": "Could you be more specific?",
        }
    }
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_factory(responses)):
        with patch("sys.stdin", new=type("S", (), {"read": lambda self: json.dumps({"prompt": "that thing"})})()):
            with patch("sys.stdout") as mock_stdout:
                hook = _load_hook("prompt_submit")
                rc = hook.main()
        assert rc == 0
        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        assert "Clarifying Question" in output
        assert "more specific" in output


# ---- post_tool_use hook -------------------------------------------------

def test_post_tool_use_saves_observation(monkeypatch):
    captured = {}
    def capture_urlopen(req, timeout=3):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        mock = MagicMock()
        mock.__enter__ = lambda self: mock
        mock.__exit__ = lambda *args: None
        mock.read.return_value = json.dumps({"id": "abc-123", "classified_type": "experience"}).encode()
        return mock
    with patch("urllib.request.urlopen", side_effect=capture_urlopen):
        with patch("sys.stdin", new=type("S", (), {"read": lambda self: json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file": "auth.py", "new_content": "fix jwt"},
            "tool_output": "file edited",
        })})()):
            hook = _load_hook("post_tool_use")
            rc = hook.main()
    assert rc == 0
    assert "memory/save" in captured["url"]
    assert captured["data"]["memory_type"] == "experience"
    assert "tool_use" in captured["data"]["tags"]


def test_post_tool_use_ignores_uninteresting_tools(monkeypatch):
    called = []
    def no_call(*args, **kwargs):
        called.append(True)
        raise AssertionError("should not have called urlopen")
    with patch("urllib.request.urlopen", side_effect=no_call):
        with patch("sys.stdin", new=type("S", (), {"read": lambda self: json.dumps({
            "tool_name": "ListMcpResourcesTool",
            "tool_input": {},
            "tool_output": "",
        })})()):
            hook = _load_hook("post_tool_use")
            rc = hook.main()
    assert rc == 0
    assert not called


def test_post_tool_use_handles_missing_tool_name(monkeypatch):
    with patch("sys.stdin", new=type("S", (), {"read": lambda self: json.dumps({})})()):
        hook = _load_hook("post_tool_use")
        rc = hook.main()
    assert rc == 0


# ---- session_end hook --------------------------------------------------

def test_session_end_saves_summary(monkeypatch):
    captured = {}
    def capture_urlopen(req, timeout=5):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        mock = MagicMock()
        mock.__enter__ = lambda self: mock
        mock.__exit__ = lambda *args: None
        mock.read.return_value = json.dumps({"id": "summary-123"}).encode()
        return mock
    with patch("urllib.request.urlopen", side_effect=capture_urlopen):
        with patch("sys.stdin", new=type("S", (), {"read": lambda self: ""})()):
            hook = _load_hook("session_end")
            rc = hook.main()
    assert rc == 0
    assert "memory/save" in captured["url"]
    assert "session_summary" in captured["data"]["tags"]


def test_session_end_handles_invalid_json(monkeypatch):
    with patch("sys.stdin", new=type("S", (), {"read": lambda self: "not json"})()):
        hook = _load_hook("session_end")
        rc = hook.main()
    assert rc == 0


# ---- plugin manifest ---------------------------------------------------

def test_plugin_manifest_lists_all_four_hooks():
    """The plugin.json lists all four lifecycle hooks."""
    p = HOOKS_DIR.parent / "plugin.json"
    assert p.exists(), "plugin.json missing"
    raw = p.read_text()
    # The manifest is a comment-friendly format — we just check the
    # hook names are present as text.
    for hook_name in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
        assert hook_name in raw, f"{hook_name} not declared in plugin.json"


def test_plugin_readme_documents_install():
    readme = HOOKS_DIR.parent / "README.md"
    assert readme.exists(), "README.md missing"
    content = readme.read_text()
    assert "Install" in content
    assert "NEXUS_URL" in content
    assert "mind_think" in content
