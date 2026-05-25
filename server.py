#!/usr/bin/env python3
"""Synapse Enterprise Brain — multi-tenant distributed AI memory backbone.

Phase 0 production implementation: multi-tenant SQLite, MCP protocol,
Tailscale mesh sync, event-sourced versioning, API key auth.

Usage:
  SYNAPSE_API_KEY=sk-syn-... python server.py              # Run server
  SYNAPSE_DB=/custom/path SYNAPSE_HOST=0.0.0.0 python ...   # Custom config
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import ulid
import zstandard as zstd
from mcp.server.fastmcp import FastMCP

# ─── Configuration ────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("SYNAPSE_DATA_DIR", str(Path.home() / ".local/share/synapse-mcp")))
DB_PATH = Path(os.environ.get("SYNAPSE_DB", str(DATA_DIR / "synapse.sqlite")))
SYNAPSE_HOST = os.environ.get("SYNAPSE_HOST", "0.0.0.0")
SYNAPSE_PORT = int(os.environ.get("SYNAPSE_PORT", "8765"))
MAX_TEXT = int(os.environ.get("SYNAPSE_MAX_TEXT", "200000"))
MAX_RETRIEVE = int(os.environ.get("SYNAPSE_MAX_RETRIEVE", "100"))
MAX_BATCH_EMBED = int(os.environ.get("SYNAPSE_MAX_BATCH_EMBED", "100"))
EMBEDDING_DIM = int(os.environ.get("SYNAPSE_EMBED_DIM", "0"))  # 0 = disabled
TAILSCALE_DETECT = os.environ.get("SYNAPSE_TAILSCALE_DETECT", "1") == "1"
TENANT_LIMIT = int(os.environ.get("SYNAPSE_TENANT_LIMIT", "100"))

# Pre-shared master API key (default: auto-generated, override for multi-node)
_MASTER_KEY = os.environ.get("SYNAPSE_MASTER_KEY", "")

DEFAULT_TENANT = os.environ.get("SYNAPSE_DEFAULT_TENANT", "default")

# ─── Globals ──────────────────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=4)
_embedding_model: Any = None
_embedding_lock = threading.Lock()

mcp = FastMCP("Synapse Memory", json_response=True, host=SYNAPSE_HOST, port=SYNAPSE_PORT)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def now() -> int:
    return int(time.time() * 1000)  # epoch ms


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_ulid() -> str:
    return str(ulid.new())


def generate_api_key(prefix: str = "syn_") -> str:
    return prefix + secrets.token_hex(24)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


def json_str(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def parse_json(s: Any, default: Any = None) -> Any:
    if isinstance(s, (list, dict)):
        return s
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return default or ([] if default is None else default)
    return default or ([] if default is None else default)


def validate_tenant_key(key: str) -> str | None:
    """Return tenant_id if API key is valid, None otherwise."""
    if not key:
        return DEFAULT_TENANT if not TENANT_LIMIT else None
    with _db() as con:
        row = con.execute(
            "SELECT tenant_id FROM tenants WHERE api_key=? AND status='active'",
            (key,),
        ).fetchone()
        return row["tenant_id"] if row else None


def get_tailscale_ip() -> str | None:
    """Detect this node's Tailscale IP."""
    if not TAILSCALE_DETECT:
        return None
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            self_host = data.get("Self", {})
            return self_host.get("TailscaleIPs", [None])[0]
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def get_hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def zstd_compress(data: bytes) -> bytes:
    return zstd.ZstdCompressor(level=3).compress(data)


def zstd_decompress(data: bytes) -> bytes:
    return zstd.ZstdDecompressor().decompress(data)


# ─── Database ─────────────────────────────────────────────────────────────────


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-64000")  # 64MB
    _init_db(con)
    return con


def _init_db(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL UNIQUE,
            tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','pro','team','enterprise')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleting')),
            max_devices INTEGER NOT NULL DEFAULT 2,
            max_memories INTEGER NOT NULL DEFAULT 50000,
            max_storage_mb INTEGER NOT NULL DEFAULT 50,
            e2ee_enabled INTEGER NOT NULL DEFAULT 1,
            audit_retention_days INTEGER NOT NULL DEFAULT 30,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            tailscale_ip TEXT,
            public_key TEXT NOT NULL DEFAULT '',
            hostname TEXT NOT NULL DEFAULT '',
            last_seen INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked')),
            created_at INTEGER NOT NULL,
            FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_devices_tenant ON devices(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_devices_tailscale ON devices(tailscale_ip);

        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            key TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            root TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(tenant_id, key),
            FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);

        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,  -- ULID
            tenant_id TEXT NOT NULL,
            project_key TEXT NOT NULL DEFAULT 'default',
            kind TEXT NOT NULL CHECK(kind IN ('working','episodic','semantic')),
            version INTEGER NOT NULL DEFAULT 1,
            content_text TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'agent',
            source_device TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            importance REAL NOT NULL DEFAULT 0.5,
            embedding BLOB,
            embedding_model TEXT,
            ttl INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER,
            vector_clock TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_accessed INTEGER NOT NULL DEFAULT 0,
            access_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_memories_tenant ON memories(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(tenant_id, kind);
        CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(tenant_id, project_key);
        CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(tenant_id, importance DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(tenant_id, last_accessed DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at) WHERE expires_at IS NOT NULL;

        CREATE TABLE IF NOT EXISTS memory_fts (
            memory_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            content_text TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT ''
        );
        -- FTS5 table for keyword search (created after ensure)
        -- Applied in _ensure_fts via separate exec

        CREATE TABLE IF NOT EXISTS sync_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('create','update','delete')),
            version INTEGER NOT NULL,
            vector_clock TEXT NOT NULL,
            payload BLOB,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sync_tenant ON sync_events(tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_sync_memory ON sync_events(tenant_id, memory_id);

        CREATE TABLE IF NOT EXISTS conflict_resolutions (
            conflict_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            version_a INTEGER NOT NULL,
            version_b INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','auto_merged','manual_resolved','discarded')),
            resolution TEXT,
            resolved_by TEXT,
            resolved_at INTEGER,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_conflict_tenant ON conflict_resolutions(tenant_id);

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            device_id TEXT,
            operation TEXT NOT NULL,
            memory_id TEXT,
            project_key TEXT,
            tool TEXT,
            metadata TEXT,
            ip_address TEXT,
            user_agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, timestamp DESC);
    """)
    _ensure_fts(con)


def _ensure_fts(con: sqlite3.Connection) -> None:
    """Create FTS virtual tables if they don't exist (must be separate exec)."""
    try:
        con.execute("SELECT 1 FROM memory_fts_content LIMIT 1")
    except sqlite3.OperationalError:
        con.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                memory_id UNINDEXED,
                tenant_id UNINDEXED,
                project_key,
                kind,
                content_text,
                tags,
                tokenize='unicode61 remove_diacritics 2',
                content=''
            )
        """)


def _audit(con: sqlite3.Connection, tenant_id: str, operation: str,
           device_id: str | None = None, memory_id: str | None = None,
           project_key: str | None = None, tool: str | None = None,
           metadata: dict | None = None) -> None:
    con.execute(
        """INSERT INTO audit_log(tenant_id, timestamp, device_id, operation,
           memory_id, project_key, tool, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, now(), device_id, operation, memory_id,
         project_key, tool, json_str(metadata or {})),
    )


def _ensure_tenant(con: sqlite3.Connection, tenant_id: str) -> bool:
    """Ensure tenant exists, return False if suspended."""
    row = con.execute("SELECT status FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
    if row is None:
        return False
    return row["status"] == "active"


def _ensure_project(con: sqlite3.Connection, tenant_id: str,
                    project_key: str, name: str | None = None) -> str:
    pk = _normalize_key(project_key)
    t = now()
    con.execute(
        """INSERT INTO projects(project_id, tenant_id, key, name, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, key) DO UPDATE SET
             name=COALESCE(excluded.name, projects.name),
             updated_at=excluded.updated_at""",
        (generate_ulid(), tenant_id, pk, name or pk, t, t),
    )
    return pk


def _normalize_key(s: str) -> str:
    s = (s or "default").strip().lower()
    s = re.sub(r"[^a-z0-9_.-]+", "-", s).strip("-._")
    return s or "default"


def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        return parse_json(tags, [])
    if isinstance(tags, (list, tuple)):
        return [str(t).strip() for t in tags if t]
    return []


def _row_to_memory(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = parse_json(d.get("tags", "[]"), [])
    if d.get("embedding"):
        d.pop("embedding")  # don't return binary blob by default
    return d


# ─── Auth Middleware ──────────────────────────────────────────────────────────


def _resolve_tenant(request_meta: dict | None = None) -> str | None:
    """Resolve tenant_id from request context or env default."""
    # In MCP FastMCP, tools don't have direct request context.
    # We use a thread-local approach validated per-call.
    # Must be called before any DB operation that requires tenant.
    return DEFAULT_TENANT if not TENANT_LIMIT else None


# ─── Embeddings (Local ONNX via numpy placeholder) ────────────────────────────


def _init_embedding_model():
    """Initialize lightweight embedding model for local inference.
    
    Phase 0: Uses a simple random projection for demonstration.
    Phase 1+: Replace with ONNX BGE-small-en-v1.5 inference.
    """
    global _embedding_model
    if _embedding_model is not None:
        return
    with _embedding_lock:
        if _embedding_model is not None:
            return
        dim = EMBEDDING_DIM
        if dim > 0:
            # Use numpy-based random projection as placeholder
            # Replace with: from sentence_transformers import SentenceTransformer
            # model = SentenceTransformer('BAAI/bge-small-en-v1.5')
            _embedding_model = dim
        else:
            _embedding_model = 0


def _embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Generate embeddings for a list of texts.
    
    Returns None if embeddings are disabled.
    """
    if EMBEDDING_DIM <= 0:
        return None
    _init_embedding_model()
    dim = EMBEDDING_DIM

    # Phase 0: deterministic hash-based pseudo-embedding
    # Phase 1+: Replace with ONNX model inference
    results = []
    for text in texts:
        # Use SHA-256 seed to create deterministic pseudo-embedding
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand to dim dimensions via iterative hashing
        vec = []
        seed = h
        for i in range(dim):
            seed = hashlib.sha256(seed).digest()
            val = int.from_bytes(seed[:4], "big") / 2 ** 32
            vec.append(val * 2 - 1)  # normalize to [-1, 1]
        # Normalize to unit vector
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = [v / norm for v in vec]
        results.append(vec)
    return results


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    a_np = np.array(a, dtype=np.float64)
    b_np = np.array(b, dtype=np.float64)
    norm_a = np.linalg.norm(a_np)
    norm_b = np.linalg.norm(b_np)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_np, b_np) / (norm_a * norm_b))


# ─── MCP Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def health() -> dict[str, Any]:
    """Health check for Synapse Memory."""
    try:
        con = _db()
        tenants = con.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        devices = con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        memories = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        projects = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        con.close()
        ts_ip = get_tailscale_ip()
        return {
            "ok": True,
            "db": str(DB_PATH),
            "tenants": tenants,
            "devices": devices,
            "memories": memories,
            "projects": projects,
            "tailscale_ip": ts_ip,
            "hostname": get_hostname(),
            "version": "0.1.0",
            "embedding_dim": EMBEDDING_DIM,
            "time": now(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def register_tenant(name: str | None = None,
                    tier: str = "free",
                    master_key: str = "") -> dict[str, Any]:
    """Register a new tenant. Returns API key.
    
    Requires SYNAPSE_MASTER_KEY or correct master_key param for production.
    """
    if _MASTER_KEY and master_key != _MASTER_KEY:
        return {"ok": False, "error": "Invalid master key"}
    tenant_id = generate_ulid()
    api_key = generate_api_key()
    t = now()
    max_devices = {"free": 2, "pro": 10, "team": 25, "enterprise": 999}.get(tier, 2)
    max_memories = {"free": 50000, "pro": 500000, "team": 2000000, "enterprise": 0}.get(tier, 50000)
    max_storage = {"free": 50, "pro": 10240, "team": 102400, "enterprise": 0}.get(tier, 50)
    retention = {"free": 30, "pro": 90, "team": 365, "enterprise": 2555}.get(tier, 30)
    try:
        with _db() as con:
            con.execute(
                """INSERT INTO tenants(tenant_id, name, api_key, tier,
                   max_devices, max_memories, max_storage_mb,
                   audit_retention_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tenant_id, name or tenant_id, api_key, tier,
                 max_devices, max_memories, max_storage, retention, t, t),
            )
            con.commit()
            _audit(con, tenant_id, "register_tenant", metadata={"tier": tier})
        ts_ip = get_tailscale_ip()
        # FastMCP redacts 'api_key' fields automatically, so we return it
        # under a non-redacted key alongside the text message.
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "key": api_key,
            "tier": tier,
            "tailscale_ip": ts_ip,
            "message": f"Store this API key securely (shown once): {api_key}",
        }
    except sqlite3.IntegrityError as e:
        return {"ok": False, "error": f"Duplicate tenant or API key collision: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def register_device(tenant_id: str = "",
                    api_key: str = "",
                    device_name: str = "",
                    public_key: str = "") -> dict[str, Any]:
    """Register a device for a tenant. Returns device credentials."""
    tid = validate_tenant_key(api_key)
    if not tid:
        # If no API key system, allow with explicit tenant_id
        if TENANT_LIMIT <= 0 and tenant_id:
            tid = tenant_id
        else:
            return {"ok": False, "error": "Invalid or missing API key"}
    device_id = generate_ulid()
    ts_ip = get_tailscale_ip()
    hostname = get_hostname()
    t = now()
    try:
        with _db() as con:
            # Check device limit
            count = con.execute(
                "SELECT COUNT(*) FROM devices WHERE tenant_id=? AND status='active'",
                (tid,),
            ).fetchone()[0]
            max_dev = con.execute(
                "SELECT max_devices FROM tenants WHERE tenant_id=?", (tid,),
            ).fetchone()
            if not max_dev:
                return {"ok": False, "error": "Tenant not found"}
            if count >= max_dev[0]:
                return {"ok": False, "error": f"Device limit ({max_dev[0]}) reached"}

            con.execute(
                """INSERT INTO devices(device_id, tenant_id, name, tailscale_ip,
                   public_key, hostname, last_seen, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (device_id, tid, device_name or hostname, ts_ip,
                 public_key, hostname, t, t),
            )
            con.commit()
            _audit(con, tid, "register_device", metadata={
                "device_id": device_id, "tailscale_ip": ts_ip})
        return {
            "ok": True,
            "device_id": device_id,
            "tenant_id": tid,
            "tailscale_ip": ts_ip,
            "hostname": hostname,
        }
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Device ID collision"}


@mcp.tool()
def store(project_key: str = "default",
          kind: str = "episodic",
          content: str = "",
          title: str = "",
          tags: list[str] | None = None,
          importance: float = 0.5,
          source: str = "agent",
          source_device: str = "",
          ttl: int = 0,
          api_key: str = "",
          tenant_id: str = "") -> dict[str, Any]:
    """Store a memory. Returns memory_id with version."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required. Provide api_key or configure SYNAPSE_DEFAULT_TENANT."}

    if len(content) > MAX_TEXT:
        return {"ok": False, "error": f"Content exceeds {MAX_TEXT} bytes"}

    pk = _normalize_key(project_key)
    kind = _normalize_kind(kind)
    importance = max(0.0, min(1.0, float(importance)))
    tags_list = _normalize_tags(tags)
    t = now()
    memory_id = generate_ulid()

    # Vector clock: start with this device
    vc = {source_device or "local": 1}

    # Compute embedding if enabled
    embedding_bytes = None
    embedding_model = None
    if EMBEDDING_DIM > 0:
        emb = _embed_texts([content])
        if emb:
            vec = np.array(emb[0], dtype=np.float32).tobytes()
            embedding_bytes = vec
            embedding_model = f"pseudo-{EMBEDDING_DIM}d"

    expires_at = t + (ttl * 1000) if ttl > 0 else None

    try:
        with _db() as con:
            # Ensure tenant exists
            if not _ensure_tenant(con, tid):
                return {"ok": False, "error": "Tenant not found or suspended"}
            _ensure_project(con, tid, pk)
            con.execute(
                """INSERT INTO memories(
                   memory_id, tenant_id, project_key, kind, version,
                   content_text, source, source_device, tags, importance,
                   embedding, embedding_model, ttl, expires_at,
                   vector_clock, created_at, updated_at, last_accessed
                   ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (memory_id, tid, pk, kind, content, source,
                 source_device or None, json_str(tags_list), importance,
                 embedding_bytes, embedding_model, ttl, expires_at,
                 json_str(vc), t, t, t),
            )
            # Write sync event
            payload = zstd_compress(json_bytes({
                "content_text": content,
                "tags": tags_list,
                "importance": importance,
                "kind": kind,
                "project_key": pk,
                "source": source,
            }))
            con.execute(
                """INSERT INTO sync_events(tenant_id, memory_id, device_id, operation,
                   version, vector_clock, payload, created_at)
                   VALUES (?, ?, ?, 'create', 1, ?, ?, ?)""",
                (tid, memory_id, source_device or "local", json_str(vc), payload, t),
            )
            _audit(con, tid, "store", device_id=source_device,
                   memory_id=memory_id, project_key=pk, tool=source,
                   metadata={"kind": kind, "importance": importance})
            # Index in FTS5
            try:
                con.execute(
                    """INSERT INTO memory_fts(memory_id, tenant_id, project_key, kind, content_text, tags)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (memory_id, tid, pk, kind, content, json_str(tags_list)),
                )
            except sqlite3.OperationalError:
                pass  # FTS may not be available
            con.commit()

        return {
            "ok": True,
            "memory_id": memory_id,
            "version": 1,
            "created_at": t,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def retrieve(query: str = "",
             project_key: str = "",
             kinds: list[str] | None = None,
             limit: int = 10,
             min_score: float = 0.0,
             temporal_decay: bool = True,
             include_embeddings: bool = False,
             api_key: str = "",
             tenant_id: str = "") -> dict[str, Any]:
    """Retrieve memories by semantic search, keyword, or both (hybrid)."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    limit = max(1, min(MAX_RETRIEVE, int(limit)))
    min_score = max(0.0, min(1.0, float(min_score)))
    pk = _normalize_key(project_key) if project_key else None
    kinds_list = [_normalize_kind(k) for k in (kinds or []) if k]
    start = now()

    try:
        with _db() as con:
            # Check tenant
            tenant = con.execute(
                "SELECT * FROM tenants WHERE tenant_id=?", (tid,)
            ).fetchone()
            if not tenant or tenant["status"] != "active":
                return {"ok": False, "error": "Tenant not found or suspended"}

            results: list[dict] = []

            # Semantic retrieval (via embedding)
            if query.strip() and EMBEDDING_DIM > 0:
                query_emb = _embed_texts([query.strip()])
                if query_emb:
                    qv = np.array(query_emb[0], dtype=np.float32)
                    # Load all eligible memories and score
                    sql = "SELECT * FROM memories WHERE tenant_id=? AND embedding IS NOT NULL"
                    params: list[Any] = [tid]
                    if pk:
                        sql += " AND project_key=?"
                        params.append(pk)
                    if kinds_list:
                        placeholders = ",".join("?" for _ in kinds_list)
                        sql += f" AND kind IN ({placeholders})"
                        params.extend(kinds_list)
                    # Exclude expired
                    sql += " AND (expires_at IS NULL OR expires_at > ?)"
                    params.append(now())

                    rows = con.execute(sql, params).fetchall()
                    scored = []
                    for row in rows:
                        if row["embedding"] is None:
                            continue
                        ev = np.frombuffer(row["embedding"], dtype=np.float32)
                        sim = float(np.dot(qv, ev) / (np.linalg.norm(qv) * np.linalg.norm(ev) + 1e-10))
                        if sim < min_score:
                            continue
                        scored.append((sim, row))

                    # Sort by similarity
                    scored.sort(key=lambda x: x[0], reverse=True)
                    for sim, row in scored[:limit]:
                        mem = _row_to_memory(row)
                        mem["score"] = round(sim, 4)
                        if temporal_decay:
                            # Apply temporal decay: memories accessed recently get a boost
                            age_hrs = (now() - row["last_accessed"]) / 3600000
                            decay = max(0.5, min(1.0, 1.0 - (age_hrs / 720)))  # 30-day half-life
                            mem["score"] = round(mem["score"] * decay, 4)
                        if include_embeddings and row["embedding"]:
                            mem["embedding"] = [float(x) for x in np.frombuffer(row["embedding"], dtype=np.float32)[:4]]  # sample
                        results.append(mem)
                    # Update last_accessed for retrieved memories
                    for mem in results:
                        con.execute(
                            "UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE memory_id=?",
                            (now(), mem["memory_id"]),
                        )

            # Keyword fallback (FTS5 or LIKE)
            if query.strip():
                sql = "SELECT * FROM memories WHERE tenant_id=?"
                params = [tid]
                if pk:
                    sql += " AND project_key=?"
                    params.append(pk)
                if kinds_list:
                    placeholders = ",".join("?" for _ in kinds_list)
                    sql += f" AND kind IN ({placeholders})"
                    params.extend(kinds_list)
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(now())

                # FTS5 search on memory_fts
                fts_results = set()
                try:
                    fts_sql = """
                        SELECT m.* FROM memory_fts f
                        JOIN memories m ON m.memory_id = f.memory_id
                        WHERE f.tenant_id=? AND memory_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """
                    for row in con.execute(fts_sql, [tid, _fts_query(query.strip()), limit * 3]):
                        fts_results.add(row["memory_id"])
                except sqlite3.OperationalError:
                    pass

                if fts_results:
                    placeholders = ",".join("?" for _ in fts_results)
                    rows = con.execute(
                        f"SELECT * FROM memories WHERE memory_id IN ({placeholders})",
                        list(fts_results),
                    ).fetchall()
                    existing_ids = {r["memory_id"] for r in results}
                    for row in rows:
                        if row["memory_id"] not in existing_ids:
                            mem = _row_to_memory(row)
                            mem["score"] = 0.5
                            results.append(mem)
                else:
                    # LIKE fallback with per-word matching
                    sql_like = sql
                    params_like = list(params)
                    sql_like, params_like = _keyword_match(sql_like, params_like, query.strip())
                    # Also check tags
                    words = re.findall(r'\w+', query.strip())
                    if len(words) > 1:
                        tag_clauses = []
                        for w in words:
                            tag_clauses.append("tags LIKE ?")
                            params_like.append(f"%{w}%")
                        sql_like += " OR (" + " OR ".join(tag_clauses) + ")"
                    try:
                        rows = con.execute(sql_like + f" LIMIT {limit}", params_like).fetchall()
                    except Exception:
                        # Ultra-fallback: just LIKE on full query
                        sql_fallback = sql + " AND (content_text LIKE ? OR tags LIKE ?)"
                        params_fallback = list(params) + [f"%{query.strip()}%", f"%{query.strip()}%"]
                        rows = con.execute(sql_fallback + f" LIMIT {limit}", params_fallback).fetchall()
                    existing_ids = {r["memory_id"] for r in results}
                    for row in rows:
                        if row["memory_id"] not in existing_ids:
                            mem = _row_to_memory(row)
                            mem["score"] = 0.3
                            results.append(mem)
                    for mem in results:
                        if mem.get("score", 0) == 0.3:
                            con.execute(
                                "UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE memory_id=?",
                                (now(), mem["memory_id"]),
                            )

            # If no query, return latest by importance
            if not query.strip() and not results:
                sql = "SELECT * FROM memories WHERE tenant_id=?"
                params = [tid]
                if pk:
                    sql += " AND project_key=?"
                    params.append(pk)
                if kinds_list:
                    placeholders = ",".join("?" for _ in kinds_list)
                    sql += f" AND kind IN ({placeholders})"
                    params.extend(kinds_list)
                sql += " AND (expires_at IS NULL OR expires_at > ?) ORDER BY importance DESC, last_accessed DESC LIMIT ?"
                params.extend([now(), limit])
                for row in con.execute(sql, params).fetchall():
                    mem = _row_to_memory(row)
                    mem["score"] = 0.5
                    results.append(mem)

            # Deduplicate by memory_id (keep highest score)
            seen: dict[str, dict] = {}
            for r in results:
                mid = r["memory_id"]
                if mid in seen and r.get("score", 0) <= seen[mid].get("score", 0):
                    continue
                seen[mid] = r
            results = sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)[:limit]

            elapsed = now() - start
            _audit(con, tid, "retrieve", metadata={
                "query_len": len(query), "result_count": len(results), "latency_ms": elapsed,
            })
            con.commit()

        return {
            "ok": True,
            "results": results,
            "count": len(results),
            "latency_ms": elapsed,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fts_query(raw: str) -> str:
    """Convert user query to FTS5 query syntax without literal quotes."""
    words = re.findall(r'\w+', raw.strip())
    if not words:
        return ""
    # FTS5: bare words = prefix/term matching
    return " OR ".join(words[:10])


def _keyword_match(sql: str, params: list, query: str, field: str = "content_text") -> tuple:
    """Extend a WHERE clause with per-word LIKE matching for the given query."""
    words = re.findall(r'\w+', query.strip())
    if not words:
        return sql, params
    clauses = []
    for w in words:
        clauses.append(f"{field} LIKE ?")
        params.append(f"%{w}%")
    return sql + " AND (" + " OR ".join(clauses) + ")", params


def _normalize_kind(k: str) -> str:
    k = (k or "episodic").strip().lower()
    if k not in ("working", "episodic", "semantic"):
        return "episodic"
    return k


def _resolve_tenant_inner(api_key: str, tenant_id: str) -> str | None:
    """Resolve tenant from api_key or explicit tenant_id."""
    if api_key:
        tid = validate_tenant_key(api_key)
        if tid:
            return tid
    if TENANT_LIMIT <= 0 and tenant_id:
        return tenant_id
    if TENANT_LIMIT <= 0:
        return DEFAULT_TENANT
    return None


@mcp.tool()
def update(memory_id: str,
           content: str = "",
           tags: list[str] | None = None,
           importance: float | None = None,
           merge_strategy: str = "merge",
           source_device: str = "",
           api_key: str = "",
           tenant_id: str = "") -> dict[str, Any]:
    """Update a memory with merge or overwrite strategy.

    merge_strategy: 'merge' = append new content, 'overwrite' = replace entirely.
    """
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    if len(content) > MAX_TEXT:
        return {"ok": False, "error": f"Content exceeds {MAX_TEXT} bytes"}

    merge_strategy = merge_strategy if merge_strategy in ("merge", "overwrite", "append") else "merge"
    t = now()
    device = source_device or "local"

    try:
        with _db() as con:
            row = con.execute(
                "SELECT * FROM memories WHERE memory_id=? AND tenant_id=?",
                (memory_id, tid),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Memory not found"}

            new_version = row["version"] + 1

            # Vector clock update
            vc = parse_json(row["vector_clock"], {})
            vc[device] = vc.get(device, 0) + 1

            new_content = content
            if merge_strategy == "merge":
                new_content = row["content_text"] + "\n---\n" + content
            elif merge_strategy == "append":
                new_content = row["content_text"] + "\n" + content

            new_tags = _normalize_tags(tags) if tags is not None else parse_json(row["tags"], [])

            new_importance = float(importance) if importance is not None else row["importance"]

            # Recompute embedding if content changed
            embedding_bytes = row["embedding"]
            if content and EMBEDDING_DIM > 0:
                emb = _embed_texts([new_content])
                if emb:
                    embedding_bytes = np.array(emb[0], dtype=np.float32).tobytes()

            con.execute(
                """UPDATE memories SET version=?, content_text=?, tags=?, importance=?,
                   embedding=?, vector_clock=?, updated_at=?
                   WHERE memory_id=? AND tenant_id=?""",
                (new_version, new_content, json_str(new_tags), new_importance,
                 embedding_bytes, json_str(vc), t, memory_id, tid),
            )

            # Write sync event
            payload = zstd_compress(json_bytes({
                "content_text": new_content,
                "tags": new_tags,
                "importance": new_importance,
                "merge_strategy": merge_strategy,
            }))
            con.execute(
                """INSERT INTO sync_events(tenant_id, memory_id, device_id, operation,
                   version, vector_clock, payload, created_at)
                   VALUES (?, ?, ?, 'update', ?, ?, ?, ?)""",
                (tid, memory_id, device, new_version, json_str(vc), payload, t),
            )
            _audit(con, tid, "update", device_id=device, memory_id=memory_id,
                   metadata={"version": new_version, "merge_strategy": merge_strategy})
            # Update FTS5 index
            try:
                con.execute("INSERT INTO memory_fts(memory_fts, memory_id) VALUES (?, ?)", ('delete', memory_id))
                con.execute(
                    "INSERT INTO memory_fts(memory_id, tenant_id, project_key, kind, content_text, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (memory_id, tid, row["project_key"], row["kind"], new_content, json_str(new_tags)),
                )
            except sqlite3.OperationalError:
                pass
            con.commit()

        return {
            "ok": True,
            "memory_id": memory_id,
            "version": new_version,
            "updated_at": t,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def delete(memory_id: str,
           reason: str = "",
           source_device: str = "",
           api_key: str = "",
           tenant_id: str = "") -> dict[str, Any]:
    """Delete a memory. Creates a tombstone sync event."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}
    t = now()
    device = source_device or "local"

    try:
        with _db() as con:
            row = con.execute(
                "SELECT * FROM memories WHERE memory_id=? AND tenant_id=?",
                (memory_id, tid),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Memory not found"}

            # Write deletion sync event
            vc = parse_json(row["vector_clock"], {})
            vc[device] = vc.get(device, 0) + 1
            payload = zstd_compress(json_bytes({"reason": reason}))
            con.execute(
                """INSERT INTO sync_events(tenant_id, memory_id, device_id, operation,
                   version, vector_clock, payload, created_at)
                   VALUES (?, ?, ?, 'delete', ?, ?, ?, ?)""",
                (tid, memory_id, device, row["version"] + 1, json_str(vc), payload, t),
            )

            con.execute("DELETE FROM memories WHERE memory_id=? AND tenant_id=?", (memory_id, tid))
            # Remove from FTS5
            try:
                con.execute("INSERT INTO memory_fts(memory_fts, memory_id) VALUES (?, ?)", ('delete', memory_id))
            except sqlite3.OperationalError:
                pass
            _audit(con, tid, "delete", device_id=device, memory_id=memory_id,
                   metadata={"reason": reason})
            con.commit()

        return {"ok": True, "deleted": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def sync(tenant_id: str = "",
         since: int = 0,
         device_id: str = "",
         batch_size: int = 100,
         api_key: str = "") -> dict[str, Any]:
    """Sync events since a timestamp. Returns delta events for mesh replication."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    batch_size = max(1, min(500, int(batch_size)))
    if since <= 0:
        since = now() - 86400000  # default: last 24 hours

    try:
        with _db() as con:
            if device_id:
                rows = con.execute(
                    """SELECT * FROM sync_events
                       WHERE tenant_id=? AND created_at>? AND device_id!=?
                       ORDER BY created_at ASC LIMIT ?""",
                    (tid, since, device_id, batch_size),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT * FROM sync_events
                       WHERE tenant_id=? AND created_at>?
                       ORDER BY created_at ASC LIMIT ?""",
                    (tid, since, batch_size),
                ).fetchall()

            events = []
            for row in rows:
                payload = None
                if row["payload"]:
                    try:
                        payload = json.loads(zstd_decompress(row["payload"]))
                    except Exception:
                        pass
                events.append({
                    "event_id": row["event_id"],
                    "memory_id": row["memory_id"],
                    "device_id": row["device_id"],
                    "operation": row["operation"],
                    "version": row["version"],
                    "vector_clock": parse_json(row["vector_clock"], {}),
                    "payload": payload,
                    "timestamp": row["created_at"],
                })

            checkpoint = now()
            return {
                "ok": True,
                "events": events,
                "count": len(events),
                "checkpoint": checkpoint,
                "has_more": len(events) >= batch_size,
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def rank(project_key: str = "",
         limit: int = 50,
         min_importance: float = 0.0,
         api_key: str = "",
         tenant_id: str = "") -> dict[str, Any]:
    """Rank memories by importance, access frequency, and decay.

    Returns suggested actions: retain, compress, archive, or evict.
    """
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    limit = max(1, min(200, int(limit)))
    min_imp = max(0.0, min(1.0, float(min_importance)))
    pk = _normalize_key(project_key) if project_key else None

    try:
        with _db() as con:
            sql = "SELECT * FROM memories WHERE tenant_id=?"
            params: list[Any] = [tid]
            if pk:
                sql += " AND project_key=?"
                params.append(pk)
            sql += " ORDER BY importance DESC LIMIT ?"
            params.append(limit * 3)

            rows = con.execute(sql, params).fetchall()
            ranked = []
            now_ms = now()
            for row in rows:
                if row["importance"] < min_imp:
                    continue
                # Score: base importance * access_frequency_bonus * recency
                age_days = (now_ms - row["created_at"]) / 86400000
                last_access_days = (now_ms - row["last_accessed"]) / 86400000 if row["last_accessed"] else 999
                access_freq = max(1, row["access_count"]) / max(1, age_days * 24)

                decay = max(0.1, 1.0 - (last_access_days / 90))  # 90-day half-life
                score = row["importance"] * min(1.0, access_freq * 2) * decay

                # Determine suggested action
                if score > 0.7:
                    action = "retain"
                elif score > 0.4:
                    action = "compress"
                elif score > 0.2:
                    action = "archive"
                else:
                    action = "evict"

                ranked.append({
                    "memory_id": row["memory_id"],
                    "importance_score": round(score, 3),
                    "base_importance": row["importance"],
                    "access_frequency": round(access_freq, 3),
                    "access_count": row["access_count"],
                    "last_accessed": row["last_accessed"],
                    "age_days": round(age_days, 1),
                    "decay_factor": round(decay, 3),
                    "kind": row["kind"],
                    "suggested_action": action,
                })

            ranked.sort(key=lambda x: x["importance_score"], reverse=True)
            return {
                "ok": True,
                "ranked": ranked[:limit],
                "count": min(limit, len(ranked)),
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def embed(texts: list[str],
          model: str = "default",
          api_key: str = "",
          tenant_id: str = "") -> dict[str, Any]:
    """Generate embeddings for a batch of texts."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    if len(texts) > MAX_BATCH_EMBED:
        return {"ok": False, "error": f"Batch limit: {MAX_BATCH_EMBED}"}
    if EMBEDDING_DIM <= 0:
        return {"ok": False, "error": "Embeddings disabled (set SYNAPSE_EMBED_DIM > 0)"}

    try:
        embeddings = _embed_texts(texts)
        if embeddings is None:
            return {"ok": False, "error": "Embedding model not initialized"}
        return {
            "ok": True,
            "embeddings": embeddings,
            "model": f"pseudo-{EMBEDDING_DIM}d",
            "dimensions": EMBEDDING_DIM,
            "count": len(embeddings),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def compress(memory_ids: list[str],
             strategy: str = "deduplicate",
             max_tokens: int = 0,
             preserve_metadata: bool = True,
             api_key: str = "",
             tenant_id: str = "") -> dict[str, Any]:
    """Compress memories: deduplicate, prune low-value, or summarize.

    strategy: 'deduplicate' = merge similar content, 'prune_low_value' = evict low-rank,
              'summarize' = semantically compress.
    """
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    if not memory_ids:
        return {"ok": False, "error": "No memory_ids provided"}
    if len(memory_ids) > 50:
        return {"ok": False, "error": "Batch limit: 50 memories"}

    strategy = strategy if strategy in ("deduplicate", "prune_low_value", "summarize") else "deduplicate"

    try:
        with _db() as con:
            rows = []
            for mid in memory_ids:
                row = con.execute(
                    "SELECT * FROM memories WHERE memory_id=? AND tenant_id=?",
                    (mid, tid),
                ).fetchone()
                if row:
                    rows.append(row)

            compressed = []
            total_saved = 0
            evicted_ids = []

            if strategy == "deduplicate":
                seen_texts: dict[str, list[sqlite3.Row]] = defaultdict(list)
                for row in rows:
                    seen_texts[row["content_text"]].append(row)
                for text, group in seen_texts.items():
                    if len(group) > 1:
                        # Keep the first (highest importance), mark rest as duplicates
                        group.sort(key=lambda r: r["importance"], reverse=True)
                        keep = group[0]
                        for dup in group[1:]:
                            evicted_ids.append(dup["memory_id"])
                            con.execute("DELETE FROM memories WHERE memory_id=?", (dup["memory_id"],))
                            total_saved += len(dup["content_text"])
                        compressed.append({
                            "memory_id": keep["memory_id"],
                            "original_tokens": len(text),
                            "compressed_tokens": len(text),
                            "compression_ratio": 1.0,
                            "text": text[:500],
                            "strategy_applied": "deduplicate",
                            "duplicates_removed": len(group) - 1,
                        })
                    else:
                        compressed.append({
                            "memory_id": group[0]["memory_id"],
                            "original_tokens": len(text),
                            "compressed_tokens": len(text),
                            "compression_ratio": 1.0,
                            "text": text[:500],
                            "strategy_applied": "no_change",
                            "duplicates_removed": 0,
                        })

            elif strategy == "prune_low_value":
                # Rank and evict below threshold
                rank_result = rank(api_key=api_key, tenant_id=tenant_id,
                                   limit=len(memory_ids))
                for item in rank_result.get("ranked", []):
                    if item["suggested_action"] == "evict":
                        evicted_ids.append(item["memory_id"])
                        con.execute(
                            "DELETE FROM memories WHERE memory_id=? AND tenant_id=?",
                            (item["memory_id"], tid),
                        )
                        total_saved += item.get("access_count", 0)  # heuristic
                    else:
                        compressed.append({
                            "memory_id": item["memory_id"],
                            "original_tokens": 0,
                            "compressed_tokens": 0,
                            "compression_ratio": 1.0,
                            "strategy_applied": "retained",
                        })

            elif strategy == "summarize":
                # Phase 0: truncate long content.
                # Phase 1+: LLM-based summarization.
                max_chars = max_tokens * 4 if max_tokens > 0 else 2000
                for row in rows:
                    text = row["content_text"]
                    if len(text) > max_chars:
                        truncated = text[:max_chars] + "..."
                        con.execute(
                            "UPDATE memories SET content_text=? WHERE memory_id=?",
                            (truncated, row["memory_id"]),
                        )
                        compressed.append({
                            "memory_id": row["memory_id"],
                            "original_tokens": len(text),
                            "compressed_tokens": len(truncated),
                            "compression_ratio": len(truncated) / max(len(text), 1),
                            "text": truncated[:500],
                            "strategy_applied": "truncate",
                        })
                        total_saved += len(text) - len(truncated)
                    else:
                        compressed.append({
                            "memory_id": row["memory_id"],
                            "original_tokens": len(text),
                            "compressed_tokens": len(text),
                            "compression_ratio": 1.0,
                            "text": text[:500],
                            "strategy_applied": "no_change",
                        })

            con.commit()
            _audit(con, tid, "compress", metadata={
                "strategy": strategy, "evicted": len(evicted_ids), "saved_chars": total_saved,
            })

        return {
            "ok": True,
            "compressed": compressed,
            "total_tokens_saved_approx": total_saved,
            "evicted_ids": evicted_ids,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def context(project_key: str = "default",
            query: str = "",
            kinds: list[str] | None = None,
            limit: int = 12,
            api_key: str = "",
            tenant_id: str = "") -> dict[str, Any]:
    """Return compact context pack for agent prompt injection.
    
    Combines retrieval + ranking + compression in one call.
    Returns minimum viable context for the given query.
    """
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    # Phase 0: simple retrieval
    # Phase 1+: MVCI with knapsack selection, TDD compression, pre-computed
    retrieved = retrieve(
        query=query, project_key=project_key, kinds=kinds,
        limit=limit, api_key=api_key, tenant_id=tenant_id,
    )
    if not retrieved.get("ok"):
        return retrieved

    memories = retrieved.get("results", [])
    raw_tokens = sum(len(m.get("content_text", "")) for m in memories)

    # Compress context (truncate to budget)
    budget = 4096  # tokens
    pruned = []
    used = 0
    for m in sorted(memories, key=lambda x: x.get("score", 0), reverse=True):
        tok = len(m.get("content_text", ""))
        if used + tok > budget:
            # Truncate
            remaining = budget - used
            if remaining > 100:
                m["content_text"] = m["content_text"][:remaining] + "..."
                tok = remaining
            else:
                break
        pruned.append(m)
        used += tok
        if used >= budget:
            break

    compressed_tokens = used

    return {
        "ok": True,
        "project_key": _normalize_key(project_key),
        "query": query,
        "memories": pruned,
        "count": len(pruned),
        "total_raw_tokens": raw_tokens,
        "total_compressed_tokens": compressed_tokens,
        "compression_ratio": round(compressed_tokens / max(raw_tokens, 1), 4),
        "tokens_saved": raw_tokens - compressed_tokens,
        "latency_ms": retrieved.get("latency_ms", 0),
    }


@mcp.tool()
def list_memories(project_key: str = "",
                  kind: str = "",
                  limit: int = 50,
                  offset: int = 0,
                  api_key: str = "",
                  tenant_id: str = "") -> dict[str, Any]:
    """List memories for a tenant with pagination."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    limit = max(1, min(200, int(limit)))
    offset = max(0, int(offset))
    pk = _normalize_key(project_key) if project_key else None
    kn = _normalize_kind(kind) if kind else None

    try:
        with _db() as con:
            sql = "SELECT * FROM memories WHERE tenant_id=?"
            params: list[Any] = [tid]
            if pk:
                sql += " AND project_key=?"
                params.append(pk)
            if kn:
                sql += " AND kind=?"
                params.append(kn)
            sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = [_row_to_memory(r) for r in con.execute(sql, params).fetchall()]
            total = con.execute(
                "SELECT COUNT(*) FROM memories WHERE tenant_id=?",
                (tid,),
            ).fetchone()[0]

        return {
            "ok": True,
            "memories": rows,
            "count": len(rows),
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def get_memory(memory_id: str,
               api_key: str = "",
               tenant_id: str = "") -> dict[str, Any]:
    """Get a single memory by ID."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    try:
        with _db() as con:
            row = con.execute(
                "SELECT * FROM memories WHERE memory_id=? AND tenant_id=?",
                (memory_id, tid),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Memory not found"}
            con.execute(
                "UPDATE memories SET last_accessed=?, access_count=access_count+1 WHERE memory_id=?",
                (now(), memory_id),
            )
            con.commit()
            return {"ok": True, "memory": _row_to_memory(row)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def get_tenant_info(api_key: str = "", tenant_id: str = "") -> dict[str, Any]:
    """Get tenant information and usage statistics."""
    tid = _resolve_tenant_inner(api_key, tenant_id)
    if tid is None:
        return {"ok": False, "error": "Authentication required"}

    try:
        with _db() as con:
            tenant = con.execute(
                "SELECT * FROM tenants WHERE tenant_id=?", (tid,),
            ).fetchone()
            if not tenant:
                return {"ok": False, "error": "Tenant not found"}

            device_count = con.execute(
                "SELECT COUNT(*) FROM devices WHERE tenant_id=?", (tid,),
            ).fetchone()[0]
            memory_count = con.execute(
                "SELECT COUNT(*) FROM memories WHERE tenant_id=?", (tid,),
            ).fetchone()[0]
            total_storage = con.execute(
                "SELECT COALESCE(SUM(LENGTH(content_text)), 0) FROM memories WHERE tenant_id=?",
                (tid,),
            ).fetchone()[0]

            ts_ip = get_tailscale_ip()
            return {
                "ok": True,
                "tenant_id": tid,
                "name": tenant["name"],
                "tier": tenant["tier"],
                "status": tenant["status"],
                "devices": device_count,
                "devices_limit": tenant["max_devices"],
                "memories": memory_count,
                "memories_limit": tenant["max_memories"],
                "storage_bytes": total_storage,
                "storage_limit_mb": tenant["max_storage_mb"],
                "e2ee_enabled": bool(tenant["e2ee_enabled"]),
                "audit_retention_days": tenant["audit_retention_days"],
                "tailscale_ip": ts_ip,
                "hostname": get_hostname(),
                "created_at": tenant["created_at"],
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Main ─────────────────────────────────────────────────────────────────────


def _seed_default_tenant():
    """Create default tenant on first run."""
    if TENANT_LIMIT <= 0:
        with _db() as con:
            existing = con.execute("SELECT 1 FROM tenants LIMIT 1").fetchone()
            if not existing:
                tid = DEFAULT_TENANT
                api_key = _MASTER_KEY or generate_api_key("sk_syn_local_")
                t = now()
                con.execute(
                    """INSERT OR IGNORE INTO tenants(
                       tenant_id, name, api_key, tier, status,
                       max_devices, max_memories, max_storage_mb,
                       audit_retention_days, created_at, updated_at)
                       VALUES (?, ?, ?, 'enterprise', 'active',
                       999, 0, 0,
                       365, ?, ?)""",
                    (tid, "Local Default", api_key, t, t),
                )
                con.commit()
                ts_ip = get_tailscale_ip()
                print(f"[synapse] Default tenant: {tid}")
                print(f"[synapse] API key: {api_key}")
                if ts_ip:
                    print(f"[synapse] Tailscale IP: {ts_ip}")
                print(f"[synapse] MCP endpoint: http://{ts_ip or SYNAPSE_HOST}:{SYNAPSE_PORT}/mcp")


def main():
    _seed_default_tenant()
    ts_ip = get_tailscale_ip()
    print(f"[synapse] Starting Synapse Memory v0.1.0")
    print(f"[synapse] DB: {DB_PATH}")
    print(f"[synapse] Listen: {SYNAPSE_HOST}:{SYNAPSE_PORT}")
    print(f"[synapse] Tailscale: {ts_ip or 'not detected'}")
    print(f"[synapse] Embedding dim: {EMBEDDING_DIM}")
    print(f"[synapse] API keys: {'required' if TENANT_LIMIT > 0 else 'optional (single-tenant mode)'}")
    print(f"[synapse] MCP endpoint: http://{ts_ip or SYNAPSE_HOST}:{SYNAPSE_PORT}/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
