"""Nexus command-line entrypoint.

Installed as the ``nexus`` console script (see pyproject.toml), this gives a
one-command start story to match competitors:

    pip install -e .
    nexus start --embedded        # SQLite + in-process worker + fakeredis
    nexus start --full            # expects external Redis + worker (production)
    nexus version
    nexus status

Embedded mode (``--embedded``, the default) uses SQLite and runs the extraction
worker inside the API process with fakeredis. It needs no external services.
"""

from __future__ import annotations

import os

import click

from nexus import __version__


@click.group()
@click.version_option(__version__, prog_name="nexus")
def main() -> None:
    """Nexus — unified agent memory server."""


@main.command()
@click.option("--port", default=None, type=int, help="Port to bind (default: NEXUS_PORT or 7777).")
@click.option("--host", default="0.0.0.0", help="Host to bind.")
@click.option("--embedded/--full", default=True,
              help="Embedded: in-process worker + fakeredis (default). Full: external Redis + worker.")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes (dev).")
def start(port: int | None, host: str, embedded: bool, reload: bool) -> None:
    """Start the Nexus memory server."""
    if embedded:
        data_dir = os.path.expanduser(os.environ.get("NEXUS_DATA_DIR", "~/.nexus"))
        os.makedirs(data_dir, exist_ok=True)
        os.environ.setdefault("EMBEDDED_MODE", "true")
        os.environ.setdefault("REDIS_URL", "fakeredis://")
        os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir}/nexus.db")
        click.echo(f"Starting Nexus in EMBEDDED mode ({data_dir}/nexus.db).")
    else:
        os.environ.setdefault("EMBEDDED_MODE", "false")

    if not embedded and not os.environ.get("DATABASE_URL"):
        click.secho("warning: DATABASE_URL is not set — Nexus needs a Postgres URL.", fg="yellow")

    import uvicorn
    from app.config import settings

    bind_port = port or settings.nexus_port
    uvicorn.run("app.main:app", host=host, port=bind_port, reload=reload)


@main.command()
def version() -> None:
    """Print the Nexus version."""
    click.echo(__version__)


@main.command()
@click.option("--url", default=None, help="Nexus base URL (default: http://localhost:NEXUS_PORT).")
def status(url: str | None) -> None:
    """Check a running Nexus server's health."""
    import httpx
    from app.config import settings

    base = url or f"http://localhost:{settings.nexus_port}"
    try:
        r = httpx.get(f"{base}/health", timeout=5.0)
        click.echo(f"{base} -> {r.status_code} {r.text[:200]}")
    except Exception as e:  # pragma: no cover - operational convenience
        click.secho(f"unreachable: {e}", fg="red")
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
