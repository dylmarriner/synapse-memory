"""Inotify-based code watcher for the nexus-api container.

Watches a directory for file changes and triggers a re-index of the
code-context layer.  Uses `inotify_simple` (pure-Python, no extra
system deps) and a small debouncer so a flurry of writes becomes one
re-index call.

Run as: `python -m app.code.watcher <repo_name> <root_path> [nexus_url]`

This is meant to be run inside the nexus-api container where it has
direct access to the file tree (the same tree the dashboard indexes).
For the host use-case, use `scripts/nexus-code-watch.sh` (mtime poll).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from typing import Optional, Set

import inotify_simple

log = logging.getLogger("nexus.code.watcher")

# File extensions we care about
WATCHED_EXTS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".rb", ".pyi",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
    ".scala", ".lua", ".php", ".ex", ".exs", ".dart",
})


class InotifyCodeWatcher:
    """A simple inotify-based watcher that triggers re-index on change.

    Usage:
        w = InotifyCodeWatcher("nexus-self", "/app")
        await w.run()  # blocks
    """

    def __init__(self, repo_name: str, root_path: str,
                 nexus_url: str = "http://127.0.0.1:7777",
                 nexus_secret: str = "nexus-memory-shared-key-2026",
                 debounce_ms: int = 1500):
        self.repo_name = repo_name
        self.root_path = Path(root_path)
        self.nexus_url = nexus_url.rstrip("/")
        self.secret = nexus_secret
        self.debounce_s = debounce_ms / 1000.0
        self._last_change: float = 0.0
        self._pending: bool = False
        self._seen_paths: Set[str] = set()
        self._inotify: Optional[inotify_simple.INotify] = None
        self._wd_to_path: dict = {}
        self._stop = asyncio.Event()

    def _is_watched(self, path: str) -> bool:
        # Skip noise: __pycache__, .git, node_modules, build dirs
        parts = path.split(os.sep)
        if any(p in ("__pycache__", ".git", "node_modules", "venv", ".venv",
                     "dist", "build", ".next", "target", "out",
                     ".pytest_cache", ".mypy_cache", ".ruff_cache",
                     "site-packages", ".tox", "node_modules") for p in parts):
            return False
        return Path(path).suffix.lower() in WATCHED_EXTS

    def _build_watch_tree(self) -> None:
        """Recursively add watches for all directories under root."""
        if not self.root_path.exists():
            log.error("root path does not exist: %s", self.root_path)
            return
        self._inotify = inotify_simple.INotify()
        # Watch everything below root (recursive)
        for dirpath, dirnames, filenames in os.walk(str(self.root_path)):
            # Skip noise dirs
            dirnames[:] = [d for d in dirnames if d not in (
                "__pycache__", ".git", "node_modules", "venv", ".venv",
                "dist", "build", ".next", "target", "out",
                ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "site-packages", ".tox",
            )]
            wd = self._inotify.add_watch(dirpath, inotify_simple.flags.MODIFY | inotify_simple.flags.CREATE | inotify_simple.flags.DELETE | inotify_simple.flags.MOVED_FROM | inotify_simple.flags.MOVED_TO)
            self._wd_to_path[wd] = dirpath

    def _schedule_reindex(self) -> None:
        """Mark that a re-index is needed, debounced."""
        now = time.monotonic()
        self._last_change = now
        self._pending = True

    async def _reindex_if_due(self) -> None:
        """Call re-index if enough time has passed since last change."""
        if not self._pending:
            return
        # Wait at least debounce_s since the last change
        if (time.monotonic() - self._last_change) < self.debounce_s:
            return
        self._pending = False
        await self._call_reindex()

    async def _call_reindex(self) -> None:
        try:
            import aiohttp  # local import to avoid hard dep
        except ImportError:
            log.warning("aiohttp not available; cannot call nexus API")
            return
        url = f"{self.nexus_url}/v1/code/repos"
        payload = {"name": self.repo_name, "root_path": str(self.root_path), "max_files": 10000}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.secret}"},
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as r:
                    if r.status == 200:
                        body = await r.json()
                        log.info(
                            "re-indexed: %d files, %d symbols, %d edges in %dms",
                            body.get("files_indexed", "?"),
                            body.get("symbols", "?"),
                            body.get("edges", "?"),
                            body.get("duration_ms", "?"),
                        )
                    else:
                        text = await r.text()
                        log.error("re-index failed: HTTP %d %s", r.status, text[:200])
        except Exception as e:
            log.error("re-index call failed: %s", e)

    async def _watch_loop(self) -> None:
        """Main inotify event loop."""
        self._build_watch_tree()
        if self._inotify is None:
            return
        log.info("watching %s for changes (debounce %dms)", self.root_path, int(self.debounce_s * 1000))
        loop = asyncio.get_event_loop()
        # Use run_in_executor because inotify_simple.read() is blocking
        def _read_blocking():
            return self._inotify.read(timeout=1000)  # 1s timeout
        while not self._stop.is_set():
            for event in await loop.run_in_executor(None, _read_blocking):
                # The path is relative to the watch descriptor
                watch_path = self._wd_to_path.get(event.wd, "")
                if not watch_path:
                    continue
                full = os.path.join(watch_path, event.path) if event.path else watch_path
                if self._is_watched(full) or os.path.isdir(full):
                    log.debug("change: %s %s", event.name, full)
                    self._schedule_reindex()
            # After each read cycle, check if a re-index is due
            await self._reindex_if_due()

    async def run(self) -> None:
        """Run the watcher.  Returns when stop() is called."""
        loop = asyncio.get_event_loop()
        # Translate SIGTERM/SIGINT into a clean stop
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass
        await self._watch_loop()

    def stop(self) -> None:
        self._stop.set()


async def _main(repo_name: str, root_path: str, nexus_url: str, nexus_secret: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    w = InotifyCodeWatcher(repo_name, root_path, nexus_url, nexus_secret)
    await w.run()


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "nexus-self"
    root = sys.argv[2] if len(sys.argv) > 2 else "/app"
    url = os.environ.get("NEXUS_URL", "http://127.0.0.1:7777")
    secret = os.environ.get("NEXUS_SECRET", "nexus-memory-shared-key-2026")
    asyncio.run(_main(repo, root, url, secret))
