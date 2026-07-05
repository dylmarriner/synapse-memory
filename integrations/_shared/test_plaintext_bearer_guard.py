"""
Tests for the plaintext-bearer auth guard.

Mirrors the algorithm from
rohitg00/agentmemory/integrations/openclaw/plugin.mjs (Apache-2.0).
"""

from integrations._shared.plaintext_bearer_guard import (
    uses_plaintext_bearer_auth,
    plaintext_bearer_auth_message,
    check_plaintext_bearer,
)


def test_loopback_with_secret_is_safe():
    assert uses_plaintext_bearer_auth("http://localhost:7777", "abc") is False
    assert uses_plaintext_bearer_auth("http://127.0.0.1:7777", "abc") is False
    assert uses_plaintext_bearer_auth("http://[::1]:7777", "abc") is False


def test_https_with_secret_is_safe():
    assert uses_plaintext_bearer_auth("https://nexus.example.com", "abc") is False


def test_remote_http_with_secret_is_dangerous():
    assert uses_plaintext_bearer_auth("http://192.168.1.5:7777", "abc") is True
    assert uses_plaintext_bearer_auth("http://nexus.example.com:7777", "abc") is True


def test_remote_http_without_secret_is_safe():
    assert uses_plaintext_bearer_auth("http://192.168.1.5:7777", None) is False
    assert uses_plaintext_bearer_auth("http://192.168.1.5:7777", "") is False


def test_invalid_url_is_safe():
    assert uses_plaintext_bearer_auth("not a url", "abc") is False


def test_check_warns_on_remote_plaintext():
    warnings = []
    check_plaintext_bearer(
        base_url="http://192.168.1.5:7777",
        secret="abc",
        warn=warnings.append,
    )
    assert len(warnings) == 1
    assert "192.168.1.5" in warnings[0]
    assert "plaintext HTTP" in warnings[0]


def test_check_throws_when_flag_set():
    import pytest
    with pytest.raises(RuntimeError, match="plaintext HTTP"):
        check_plaintext_bearer(
            base_url="http://192.168.1.5:7777",
            secret="abc",
            warn=lambda m: None,
            env={"NEXUS_REQUIRE_HTTPS": "1"},
        )


def test_check_silent_on_loopback():
    warnings = []
    check_plaintext_bearer(
        base_url="http://localhost:7777",
        secret="abc",
        warn=warnings.append,
    )
    assert warnings == []


def test_check_silent_on_https():
    warnings = []
    check_plaintext_bearer(
        base_url="https://nexus.example.com",
        secret="abc",
        warn=warnings.append,
    )
    assert warnings == []


def test_check_silent_on_no_secret():
    warnings = []
    check_plaintext_bearer(
        base_url="http://192.168.1.5:7777",
        secret="",
        warn=warnings.append,
    )
    assert warnings == []


def test_message_contains_url():
    msg = plaintext_bearer_auth_message("http://10.0.0.1:7777")
    assert "10.0.0.1:7777" in msg
    assert "HTTPS" in msg or "SSH" in msg
