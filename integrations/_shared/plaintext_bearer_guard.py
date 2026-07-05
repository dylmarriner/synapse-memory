"""
Plaintext-bearer auth guard — ported from rohitg00/agentmemory.
Python counterpart to plaintext-bearer-guard.ts.

Warns (or, with NEXUS_REQUIRE_HTTPS=1, throws) when a memory server is
configured with a secret (bearer token) over plaintext HTTP to a
non-loopback host.
"""

from __future__ import annotations
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalized_hostname(hostname: str) -> str:
    return hostname.strip("[]").lower()


def uses_plaintext_bearer_auth(base_url: str, secret: Optional[str]) -> bool:
    if not secret:
        return False
    try:
        parsed = urlparse(base_url)
    except Exception:
        return False
    if parsed.scheme != "http":
        return False
    return normalized_hostname(parsed.hostname or "") not in LOOPBACK_HOSTS


def plaintext_bearer_auth_message(base_url: str) -> str:
    return (
        f"Nexus: secret is configured for plaintext HTTP to {base_url}. "
        "Bearer tokens and memory payloads can be observed on the network; "
        "use HTTPS or an SSH tunnel."
    )


def check_plaintext_bearer(
    base_url: str,
    secret: Optional[str],
    warn: Callable[[str], None],
    env: Optional[Mapping[str, str]] = None,
    flag: str = "NEXUS_REQUIRE_HTTPS",
) -> None:
    """Warn once (or throw) if base_url is plaintext HTTP with a secret.

    - Silent when no secret is set, or when the host is loopback, or
      when the scheme is https.
    - Warns (once per process) otherwise.
    - Throws when the `flag` env var is "1" — for production deploys.
    """
    if not uses_plaintext_bearer_auth(base_url, secret):
        return
    e = dict(env) if env is not None else None
    flag_value = (e or {}).get(flag, "") if e is not None else ""
    if e is None:
        import os
        flag_value = os.environ.get(flag, "")
    if flag_value == "1":
        raise RuntimeError(plaintext_bearer_auth_message(base_url))
    # warn-once pattern is the caller's responsibility; they pass a
    # deduped warn callable.
    warn(plaintext_bearer_auth_message(base_url))
