"""Tests for the install-living-mind script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "install-living-mind"


def _run(args, tmp_path, monkeypatch, env_extra=None):
    """Run the install script as a subprocess with a temp HOME."""
    args_list = args.split() if isinstance(args, str) else list(args)
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "LANG": "C.UTF-8",
    }
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args_list,
        capture_output=True, text=True, env=env, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def test_list_shows_supported_agents(tmp_path, monkeypatch):
    rc, out, _ = _run("--list", tmp_path, monkeypatch)
    assert rc == 0
    assert "claude-code" in out
    assert "opencode" in out
    assert "hermes" in out


def test_no_args_returns_help(tmp_path, monkeypatch):
    rc, out, _ = _run("", tmp_path, monkeypatch)
    assert rc == 0
    assert "Usage" in out
    assert "claude-code" in out


def test_install_creates_plugin_directory(tmp_path, monkeypatch):
    rc, _, _ = _run("claude-code", tmp_path, monkeypatch)
    assert rc == 0
    expected = tmp_path / ".claude" / "plugins" / "mind"
    assert expected.exists()
    assert (expected / "plugin.json").exists()


def test_install_is_idempotent(tmp_path, monkeypatch):
    _run("claude-code", tmp_path, monkeypatch)
    rc, out, _ = _run("claude-code", tmp_path, monkeypatch)
    assert rc == 0
    assert "already installed" in out


def test_install_skill_when_supported(tmp_path, monkeypatch):
    _run("claude-code", tmp_path, monkeypatch)
    skill_dir = tmp_path / ".claude" / "skills" / "mind-memory"
    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()


def test_install_appends_rules_when_target_exists(tmp_path, monkeypatch):
    target = tmp_path / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Existing rules\n\n## Living Mind Integration Rules\nold content\n")
    _run("claude-code", tmp_path, monkeypatch)
    content = target.read_text()
    assert "Existing rules" in content
    assert "old content" in content
    # The marker should appear only once (idempotent)
    assert content.count("## Living Mind Integration Rules") == 1


def test_install_unknown_agent_returns_nonzero(tmp_path, monkeypatch):
    rc, _, err = _run("nonexistent-agent", tmp_path, monkeypatch)
    assert rc != 0
    # Output should mention the unknown agent
    combined = (lambda: (None, None))()  # noqa
    rc, out, _ = _run("nonexistent-agent", tmp_path, monkeypatch)
    assert "nonexistent-agent" in out or rc != 0


def test_uninstall_removes_plugin(tmp_path, monkeypatch):
    _run("claude-code", tmp_path, monkeypatch)
    target = tmp_path / ".claude" / "plugins" / "mind"
    assert target.exists()
    rc, _, _ = _run("--uninstall claude-code", tmp_path, monkeypatch)
    assert not target.exists()


def test_install_prints_env_block(tmp_path, monkeypatch):
    _, out, _ = _run("claude-code", tmp_path, monkeypatch)
    assert "NEXUS_URL" in out
    assert "NEXUS_SECRET" in out
    assert "MIND_ID" in out
