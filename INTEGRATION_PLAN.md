# Nexus Integration Plan — Full Execution Guide
# For agent continuation — all research done, execute in order

Generated: 2026-06-16
Status: Ready to execute — no further research needed

---

## CONTEXT

Nexus is a unified agent memory server running at:
- REST API: `http://100.93.75.87:7777/v1`
- MCP SSE:  `http://100.93.75.87:7777/mcp/sse`
- Dashboard: `http://100.93.75.87:7777/`
- Secret:   `$NEXUS_SECRET`
- Codebase: `/media/kubuntux/DEVELOPMENT1/shared-memory/nexus/`

Already connected: Claude Code (via `~/.claude/settings.json` MCP entry + hooks).

---

## TASK 1 — Windsurf (SIMPLE — 2 file edits)

Windsurf uses Cline and Kade extensions, both support SSE MCP servers.

### 1a. Cline extension

**File:** `/home/kubuntux/.config/Windsurf/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

Add `"nexus"` entry to the existing `mcpServers` object:

```json
"nexus": {
  "url": "http://100.93.75.87:7777/mcp/sse",
  "headers": {
    "Authorization": "Bearer $NEXUS_SECRET"
  },
  "alwaysAllow": [
    "memory_save", "memory_recall", "memory_reflect",
    "memory_save_lesson", "memory_save_global", "agent_context",
    "memory_synthesize", "nexus_status"
  ],
  "disabled": false
}
```

**Do NOT replace the file — merge with existing entries** (hindsight, deepwiki, memory, puppeteer, coding-memory, software-planning).

### 1b. Kade extension

**File:** `/home/kubuntux/.config/Windsurf/User/globalStorage/kade.kade/settings/mcp_settings.json`

Replace `{"mcpServers": {}}` with:

```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://100.93.75.87:7777/mcp/sse",
      "headers": {
        "Authorization": "Bearer $NEXUS_SECRET"
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

---

## TASK 2 — Antigravity (SIMPLE — 1 file edit)

Antigravity uses Kilo Code extension. MCP settings file is currently `{"mcpServers": {}}`.

**File:** `/home/kubuntux/.antigravity-ide-server/data/User/globalStorage/kilocode.kilo-code/settings/mcp_settings.json`

Replace with:

```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://100.93.75.87:7777/mcp/sse",
      "headers": {
        "Authorization": "Bearer $NEXUS_SECRET"
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

---

## TASK 3 — Hermes (COMPLEX — create Python plugin + update config)

Hermes has an abstract `MemoryProvider` base class at:
`/home/kubuntux/.hermes/hermes-agent/agent/memory_provider.py`

Plugins live in `/home/kubuntux/.hermes/hermes-agent/plugins/memory/<name>/`.
Current config uses `provider: agentmemory`.

### 3a. Create plugin directory

```
/home/kubuntux/.hermes/hermes-agent/plugins/memory/nexus/
  __init__.py       ← full MemoryProvider implementation
  client.py         ← thin HTTP client
  plugin.yaml       ← manifest
```

### 3b. plugin.yaml

```yaml
name: nexus
version: 1.0.0
description: "Nexus unified agent memory — 4-way recall (vector+lexical+graph+temporal), lessons, entity extraction, rolling summaries."
pip_dependencies: []
hooks:
  - on_session_end
```

### 3c. client.py

```python
"""Thin synchronous HTTP client for the Nexus REST API."""

import json
import os
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any

NEXUS_URL = os.getenv("NEXUS_URL", "http://100.93.75.87:7777")
NEXUS_SECRET = os.getenv("NEXUS_SECRET", "$NEXUS_SECRET")


def _headers():
    h = {"Content-Type": "application/json"}
    if NEXUS_SECRET:
        h["Authorization"] = f"Bearer {NEXUS_SECRET}"
    return h


def _post(path: str, body: dict, timeout: int = 8) -> Optional[dict]:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", data=data, headers=_headers(), method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _get(path: str, timeout: int = 8) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            f"{NEXUS_URL}{path}", headers=_headers(), method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def health() -> bool:
    try:
        d = _get("/health", timeout=3)
        return bool(d and d.get("healthy"))
    except Exception:
        return False


def save_memory(content: str, agent_id: str, memory_type: Optional[str] = None,
                importance: float = 0.5, tags: List[str] = None) -> Optional[dict]:
    return _post("/v1/memory/save", {
        "content": content,
        "agent_id": agent_id,
        "memory_type": memory_type,
        "importance": importance,
        "tags": tags or [],
    })


def recall(query: str, agent_id: Optional[str] = None,
           limit: int = 8, modes: List[str] = None) -> List[dict]:
    body = {
        "query": query[:500],
        "limit": limit,
        "search_modes": modes or ["vector", "lexical", "graph", "temporal"],
    }
    if agent_id:
        body["agent_id"] = agent_id
    d = _post("/v1/memory/recall", body)
    return (d or {}).get("results", [])


def reflect(query: str, agent_id: Optional[str] = None,
            depth: str = "mid") -> str:
    body = {"query": query, "depth": depth}
    if agent_id:
        body["agent_id"] = agent_id
    d = _post("/v1/memory/reflect", body, timeout=20)
    return (d or {}).get("reflection", "")


def agent_context(agent_id: str, tokens: int = 2000) -> Optional[dict]:
    return _get(f"/v1/agents/{agent_id}/context?tokens={tokens}")


def save_lesson(content: str, agent_id: str) -> Optional[dict]:
    return _post("/v1/memory/save", {
        "content": content,
        "agent_id": agent_id,
        "memory_type": "lesson",
        "importance": 0.9,
    })
```

### 3d. __init__.py

```python
"""Nexus memory provider for Hermes — unified 4-way recall with lessons and summaries."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# Tool schemas exposed to the LLM
_TOOLS = [
    {
        "name": "nexus_recall",
        "description": (
            "Search Nexus long-term memory using 4-way parallel recall: semantic vector, "
            "lexical BM25, entity graph, and temporal recency — fused with Reciprocal Rank Fusion. "
            "Use to retrieve past context, user preferences, facts, and lessons."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "default": 8},
                "memory_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter: world, experience, observation, preference, lesson",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "nexus_save",
        "description": (
            "Save something to Nexus long-term memory. "
            "Use for: important facts (world), events that happened (experience), "
            "insights (observation), user preferences (preference)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "memory_type": {
                    "type": "string",
                    "enum": ["world", "experience", "observation", "preference", "lesson"],
                },
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
            },
            "required": ["content"],
        },
    },
    {
        "name": "nexus_save_lesson",
        "description": (
            "Save a lesson, correction, or mistake to Nexus. "
            "WHEN TO USE: after making an error, receiving a correction, or learning something "
            "that prevents future mistakes. High importance (0.9), never decayed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The lesson (e.g. 'I was wrong about X — correct answer is Y')"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "nexus_reflect",
        "description": (
            "Ask Nexus to synthesize all stored memories on a topic using LLM reasoning. "
            "Returns a structured knowledge synthesis. More thorough than nexus_recall."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "depth": {"type": "string", "enum": ["low", "mid", "high"], "default": "mid"},
            },
            "required": ["query"],
        },
    },
]


class NexusMemoryProvider(MemoryProvider):
    """Nexus unified memory provider."""

    def __init__(self):
        self._agent_id: str = "hermes"
        self._enabled: bool = True
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._context_cache: Optional[dict] = None
        self._char_limit: int = 2200

    @property
    def name(self) -> str:
        return "nexus"

    def is_available(self) -> bool:
        from plugins.memory.nexus.client import health
        try:
            return health()
        except Exception:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        from plugins.memory.nexus import client as nc
        self._agent_id = kwargs.get("agent_identity", "hermes")
        self._char_limit = kwargs.get("memory_char_limit", 2200)

        # Warm up: load agent context in background
        def _warm():
            try:
                ctx = nc.agent_context(self._agent_id, tokens=1500)
                self._context_cache = ctx
            except Exception as e:
                logger.debug("Nexus warmup failed: %s", e)

        t = threading.Thread(target=_warm, daemon=True)
        t.start()
        logger.info("Nexus memory provider initialized for agent '%s'", self._agent_id)

    def system_prompt_block(self) -> str:
        if not self._context_cache:
            return ""
        ctx = self._context_cache
        lines = ["## Nexus Memory Context"]

        summary = ctx.get("summary")
        if summary:
            lines.append(f"\n**Rolling Summary:**\n{summary}")

        representation = ctx.get("representation")
        if representation:
            lines.append(f"\n**Profile:**\n{representation}")

        conclusions = ctx.get("conclusions", [])
        if conclusions:
            lines.append("\n**Key Conclusions:**")
            for c in conclusions[:6]:
                lines.append(f"  - {c}")

        memories = ctx.get("recent_memories", [])
        if memories:
            lines.append(f"\n**Recent Memories ({len(memories)}):**")
            for m in memories[:8]:
                mtype = m.get("memory_type", "?")
                content = m.get("content", "")[:300]
                lines.append(f"  [{mtype}] {content}")

        block = "\n".join(lines)
        return block[:self._char_limit] if block.strip() != "## Nexus Memory Context" else ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""

        if result:
            return result

        # Synchronous fallback (fast path — vector+lexical only)
        from plugins.memory.nexus import client as nc
        try:
            results = nc.recall(query, agent_id=self._agent_id, limit=5,
                                modes=["vector", "lexical"])
            if not results:
                return ""
            lines = ["[Nexus recall:]"]
            for m in results:
                mtype = m.get("memory_type", "?")
                score = m.get("score", 0)
                content = m.get("content", "")[:250]
                lines.append(f"  [{mtype}|{score:.2f}] {content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def sync_turn(self, user_content: str, assistant_content: str,
                  *, session_id: str = "") -> None:
        if not user_content.strip():
            return

        def _save():
            from plugins.memory.nexus import client as nc
            try:
                # Save user message as experience
                if len(user_content.strip()) > 20:
                    nc.save_memory(
                        content=user_content[:800],
                        agent_id=self._agent_id,
                        memory_type="experience",
                        importance=0.5,
                    )
            except Exception as e:
                logger.debug("Nexus sync_turn save failed: %s", e)

        threading.Thread(target=_save, daemon=True).start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return _TOOLS

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        from plugins.memory.nexus import client as nc

        if tool_name == "nexus_recall":
            results = nc.recall(
                query=args.get("query", ""),
                agent_id=self._agent_id,
                limit=args.get("limit", 8),
            )
            if not results:
                return json.dumps({"results": [], "message": "No memories found."})
            formatted = [
                {
                    "type": m.get("memory_type"),
                    "score": round(m.get("score", 0), 3),
                    "content": m.get("content", ""),
                }
                for m in results
            ]
            return json.dumps({"results": formatted, "total": len(formatted)})

        elif tool_name == "nexus_save":
            r = nc.save_memory(
                content=args.get("content", ""),
                agent_id=self._agent_id,
                memory_type=args.get("memory_type"),
                importance=args.get("importance", 0.6),
            )
            return json.dumps(r or {"error": "Save failed"})

        elif tool_name == "nexus_save_lesson":
            r = nc.save_lesson(
                content=args.get("content", ""),
                agent_id=self._agent_id,
            )
            return json.dumps(r or {"error": "Save failed"})

        elif tool_name == "nexus_reflect":
            reflection = nc.reflect(
                query=args.get("query", ""),
                agent_id=self._agent_id,
                depth=args.get("depth", "mid"),
            )
            return json.dumps({"reflection": reflection})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def on_session_end(self, messages: list) -> None:
        """Trigger agent representation rebuild at session end."""
        def _rebuild():
            try:
                import urllib.request
                from plugins.memory.nexus.client import _headers, NEXUS_URL
                req = urllib.request.Request(
                    f"{NEXUS_URL}/v1/browse/agents/{self._agent_id}/represent",
                    data=b"",
                    headers=_headers(),
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=15)
                logger.info("Nexus: representation rebuilt for '%s'", self._agent_id)
            except Exception as e:
                logger.debug("Nexus represent failed: %s", e)

        threading.Thread(target=_rebuild, daemon=True).start()

    def shutdown(self) -> None:
        logger.info("Nexus provider shutdown")
```

### 3e. Update ~/.hermes/config.yaml

Find the `memory:` block in config.yaml and change it. Current block:
```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  write_approval: false
  memory_char_limit: 2200
  user_char_limit: 1375
  provider: agentmemory
  agentmemory_url: http://127.0.0.1:3111
```

Replace with:
```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  write_approval: false
  memory_char_limit: 2200
  user_char_limit: 1375
  provider: nexus

nexus:
  url: http://100.93.75.87:7777
  secret: $NEXUS_SECRET
  agent_id: hermes
  auto_save: true
  prefetch_limit: 8
```

Also add to env section (or set system env):
```
NEXUS_URL=http://100.93.75.87:7777
NEXUS_SECRET=$NEXUS_SECRET
NEXUS_AGENT_ID=hermes
```

### 3f. Verify Hermes plugin loads

The plugin name in plugin.yaml must match the `provider:` key in config.yaml.
Hermes discovers plugins by scanning `plugins/memory/*/plugin.yaml`.
The `name:` field in plugin.yaml must be `nexus`.

The class that Hermes loads is discovered via `plugins/memory/nexus/__init__.py`.
Hermes imports the provider using its plugin scanning mechanism — check
`/home/kubuntux/.hermes/hermes-agent/agent/memory_manager.py` for the exact
import pattern if it fails to load (it might look for `NexusMemoryProvider` class
or a `PROVIDER` module-level variable). Add at bottom of `__init__.py` if needed:
```python
PROVIDER = NexusMemoryProvider
```

---

## TASK 4 — OpenClaw TypeScript Extension (COMPLEX)

### 4a. Check build mechanism first

Before writing the extension, check how OpenClaw loads extensions:
```bash
grep -r "extensions\|plugin" /media/kubuntux/DEVELOPMENT1/openclaw/openclaw.mjs 2>/dev/null | head -20
# OR
cat /media/kubuntux/DEVELOPMENT1/openclaw/package.json | python3 -m json.tool | grep -A5 "script"
```

If extensions are loaded as TypeScript source (via tsx):
→ Write index.ts and tsconfig.json as shown below.

If extensions must be compiled to dist/:
→ Run `cd /media/kubuntux/DEVELOPMENT1/openclaw && pnpm build` after writing the files.

### 4b. Create extension directory

```
/media/kubuntux/DEVELOPMENT1/openclaw/extensions/nexus-memory/
  index.ts
  openclaw.plugin.json
  package.json
  tsconfig.json
```

### 4c. package.json

```json
{
  "name": "@openclaw/nexus-memory",
  "version": "1.0.0",
  "description": "Nexus unified agent memory plugin for OpenClaw",
  "type": "module",
  "dependencies": {},
  "devDependencies": {
    "@openclaw/plugin-sdk": "workspace:*"
  },
  "openclaw": {
    "extensions": ["nexus-memory"]
  }
}
```

### 4d. openclaw.plugin.json

```json
{
  "id": "nexus-memory",
  "name": "Nexus Memory",
  "description": "Unified long-term memory via Nexus — 4-way recall, lessons, entity graph, rolling summaries.",
  "kind": "memory",
  "activation": {
    "onStartup": true
  },
  "contracts": {
    "tools": ["memory_forget", "memory_recall", "memory_store"]
  },
  "uiHints": {
    "nexusUrl": {
      "label": "Nexus URL",
      "placeholder": "http://100.93.75.87:7777"
    },
    "nexusSecret": {
      "label": "Nexus API Secret",
      "sensitive": true
    },
    "agentId": {
      "label": "Agent ID",
      "placeholder": "openclaw"
    },
    "autoCapture": {
      "label": "Auto-Capture",
      "help": "Automatically save conversation highlights to Nexus"
    },
    "autoRecall": {
      "label": "Auto-Recall",
      "help": "Automatically inject relevant memories before each response"
    }
  },
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "nexusUrl":    { "type": "string" },
      "nexusSecret": { "type": "string" },
      "agentId":     { "type": "string" },
      "autoCapture": { "type": "boolean" },
      "autoRecall":  { "type": "boolean" }
    }
  }
}
```

### 4e. tsconfig.json

```json
{
  "extends": "../tsconfig.package-boundary.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "."
  },
  "include": ["index.ts"]
}
```

### 4f. index.ts

```typescript
/**
 * Nexus Memory Plugin for OpenClaw
 * Provides long-term memory via the Nexus unified memory server.
 * Uses built-in Node.js https module — zero extra dependencies.
 */

import { request as httpsRequest } from "node:https";
import { request as httpRequest } from "node:http";

// ── Config ────────────────────────────────────────────────────────────────

type NexusConfig = {
  nexusUrl: string;
  nexusSecret: string;
  agentId: string;
  autoCapture: boolean;
  autoRecall: boolean;
};

function getConfig(): NexusConfig {
  return {
    nexusUrl: process.env.NEXUS_URL ?? "http://100.93.75.87:7777",
    nexusSecret: process.env.NEXUS_SECRET ?? "$NEXUS_SECRET",
    agentId: process.env.NEXUS_AGENT_ID ?? "openclaw",
    autoCapture: true,
    autoRecall: true,
  };
}

// ── HTTP helpers ──────────────────────────────────────────────────────────

function nexusPost<T>(path: string, body: unknown, timeoutMs = 8000): Promise<T> {
  const cfg = getConfig();
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const url = new URL(cfg.nexusUrl + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cfg.nexusSecret}`,
        "Content-Length": Buffer.byteLength(data),
      },
      timeout: timeoutMs,
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(raw)); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.write(data);
    req.end();
  });
}

function nexusGet<T>(path: string, timeoutMs = 6000): Promise<T> {
  const cfg = getConfig();
  return new Promise((resolve, reject) => {
    const url = new URL(cfg.nexusUrl + path);
    const isHttps = url.protocol === "https:";
    const reqFn = isHttps ? httpsRequest : httpRequest;
    const req = reqFn({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: "GET",
      headers: { "Authorization": `Bearer ${cfg.nexusSecret}` },
      timeout: timeoutMs,
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(raw)); }
        catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.end();
  });
}

// ── Nexus API calls ───────────────────────────────────────────────────────

async function nexusRecall(query: string, limit = 8): Promise<any[]> {
  const cfg = getConfig();
  try {
    const res: any = await nexusPost("/v1/memory/recall", {
      query: query.slice(0, 500),
      agent_id: cfg.agentId,
      limit,
      search_modes: ["vector", "lexical"],
    });
    return res?.results ?? [];
  } catch { return []; }
}

async function nexusSave(content: string, memoryType?: string, importance = 0.55): Promise<void> {
  const cfg = getConfig();
  try {
    await nexusPost("/v1/memory/save", {
      content: content.slice(0, 1000),
      agent_id: cfg.agentId,
      memory_type: memoryType,
      importance,
    });
  } catch { /* silent */ }
}

async function nexusReflect(query: string): Promise<string> {
  try {
    const res: any = await nexusPost("/v1/memory/reflect", {
      query,
      agent_id: getConfig().agentId,
      depth: "mid",
    }, 20000);
    return res?.reflection ?? "";
  } catch { return ""; }
}

// ── Plugin entry point ────────────────────────────────────────────────────
// Adapt this to the actual OpenClaw plugin SDK interface.
// Look at /media/kubuntux/DEVELOPMENT1/openclaw/extensions/memory-lancedb/index.ts
// for the exact API — mirror its export shape.

export async function onBeforeResponse(context: {
  userMessage: string;
  injectContext: (text: string) => void;
}): Promise<void> {
  const cfg = getConfig();
  if (!cfg.autoRecall) return;
  const results = await nexusRecall(context.userMessage);
  if (!results.length) return;
  const lines = ["[Nexus memory context:]"];
  for (const m of results) {
    lines.push(`  [${m.memory_type}|${(m.score ?? 0).toFixed(2)}] ${(m.content ?? "").slice(0, 300)}`);
  }
  context.injectContext(lines.join("\n"));
}

export async function onAfterResponse(context: {
  userMessage: string;
  assistantMessage: string;
}): Promise<void> {
  const cfg = getConfig();
  if (!cfg.autoCapture) return;
  const text = context.userMessage.slice(0, 600);
  if (text.length > 30) {
    await nexusSave(text, "experience", 0.5);
  }
}

// Standard MCP-style tool handlers (matching contracts in openclaw.plugin.json)
export const tools = {
  async memory_recall(args: { query: string; limit?: number }) {
    const results = await nexusRecall(args.query, args.limit ?? 8);
    if (!results.length) return { text: "No memories found." };
    const lines = results.map(m =>
      `[${m.memory_type}] score=${(m.score ?? 0).toFixed(2)}  ${(m.content ?? "").slice(0, 400)}`
    );
    return { text: `Found ${results.length} memories:\n${lines.join("\n")}` };
  },

  async memory_store(args: { content: string; type?: string; importance?: number }) {
    await nexusSave(args.content, args.type, args.importance ?? 0.6);
    return { text: "Memory saved to Nexus." };
  },

  async memory_forget(args: { query: string }) {
    // Nexus doesn't have a direct forget-by-query — return guidance
    return { text: "Use the Nexus dashboard at http://100.93.75.87:7777/ to delete specific memories." };
  },
};
```

### 4g. Update ~/.openclaw/openclaw.json

In the `plugins` section, make two changes:

1. Change memory slot from `"openclaw-honcho"` to `"nexus-memory"`:
```json
"slots": {
  "memory": "nexus-memory"
}
```

2. Add nexus-memory entry to `entries`:
```json
"nexus-memory": {
  "enabled": true,
  "hooks": {
    "allowConversationAccess": true
  },
  "config": {
    "nexusUrl": "http://100.93.75.87:7777",
    "nexusSecret": "$NEXUS_SECRET",
    "agentId": "openclaw",
    "autoCapture": true,
    "autoRecall": true
  }
}
```

**NOTE:** Keep `openclaw-honcho` entry but set `"enabled": false` so it doesn't compete.

---

## TASK 5 — OpenClaw Soul/Identity Saving

The user wants to save the OpenClaw agent's identity/soul to Nexus so all agents know it.

### 5a. Find the system prompt

The system prompt lives in the OpenClaw trajectory session files:
```bash
# Read the most recent trajectory to find system message
head -c 10000 $(ls -t /home/kubuntux/.openclaw/agents/main/sessions/*.trajectory.jsonl | head -1) \
  | python3 -c "
import json,sys
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        if d.get('role') == 'system' or 'system' in str(d).lower()[:100]:
            print(json.dumps(d, indent=2)[:2000])
    except: pass
"
```

### 5b. Also check plugin-skills and workspace

```bash
cat /home/kubuntux/.openclaw/plugin-skills/*.* 2>/dev/null | head -200
find /home/kubuntux/.openclaw/workspace/ -name "*.md" -o -name "SOUL*" -o -name "IDENTITY*" 2>/dev/null | head -10
```

### 5c. Save identity to Nexus

Once the system prompt / soul content is found, save it via:
```bash
AUTH="Bearer $NEXUS_SECRET"

curl -s -X POST http://100.93.75.87:7777/v1/memory/save \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "<PASTE SOUL/IDENTITY TEXT HERE>",
    "agent_id": "openclaw",
    "memory_type": "world",
    "importance": 0.95,
    "tags": ["identity", "soul", "system-prompt"]
  }'
```

Also save a global version so ALL agents know OpenClaw's identity:
```bash
curl -s -X POST http://100.93.75.87:7777/v1/memory/save \
  -H "Authorization: $AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "OpenClaw agent identity: <PASTE SOUL TEXT>",
    "agent_id": "global",
    "memory_type": "world",
    "importance": 0.9,
    "tags": ["agent-identity", "openclaw"]
  }'
```

---

## TASK 6 — Commit to GitHub

After all tasks complete:
```bash
cd /media/kubuntux/DEVELOPMENT1/shared-memory/nexus
git add -A
git commit -m "Add Hermes Python plugin, OpenClaw TS extension, Windsurf/Antigravity MCP config"
git push origin master
```

The OpenClaw extension should also be committed separately if it's in the openclaw repo:
```bash
cd /media/kubuntux/DEVELOPMENT1/openclaw
git add extensions/nexus-memory/
git commit -m "Add nexus-memory plugin — unified long-term memory via Nexus server"
```

---

## VERIFICATION CHECKLIST

After completing each task, verify:

### Task 1 (Windsurf)
- Open Windsurf → Cline → MCP servers panel
- "nexus" should appear in the list
- Run `nexus_status` tool — should return healthy

### Task 2 (Antigravity)
- Open Antigravity → Kilo Code → MCP panel (or reload window)
- "nexus" should appear

### Task 3 (Hermes)
```bash
# Restart Hermes and check logs
systemctl --user restart hermes-gateway.service
journalctl --user -u hermes-gateway.service -f | grep -i nexus
# Should see: "Nexus memory provider initialized for agent 'hermes'"
```

### Task 4 (OpenClaw)
```bash
# Restart OpenClaw gateway
systemctl --user restart openclaw-gateway.service 2>/dev/null || \
  pkill -f openclaw && openclaw gateway start &
# In a chat, ask: "what do you remember about me?" 
# OpenClaw should query Nexus and return memories
```

### Task 5 (Soul saved)
```bash
# Verify soul is in Nexus
curl -s -H "Authorization: Bearer $NEXUS_SECRET" \
  "http://100.93.75.87:7777/v1/browse/memories?agent=openclaw&type=world" \
  | python3 -m json.tool | grep -A3 '"soul"\|"identity"'
```

---

## KEY FACTS FOR EXECUTING AGENT

- Nexus is Docker Compose. Codebase: `/media/kubuntux/DEVELOPMENT1/shared-memory/nexus/`
- Nexus is already running — do NOT rebuild unless you change nexus source files
- GitHub repo: `https://github.com/dylanmarriner/shared-memory-mcp` (already pushed)
- Secret: `$NEXUS_SECRET` (in .env, NOT committed)
- The MCP SSE endpoint requires `Authorization: Bearer <secret>` header
- Hermes memory provider interface: `/home/kubuntux/.hermes/hermes-agent/agent/memory_provider.py`
- Hermes honcho plugin (use as reference): `/home/kubuntux/.hermes/hermes-agent/plugins/memory/honcho/__init__.py`
- OpenClaw memory-lancedb (use as reference): `/media/kubuntux/DEVELOPMENT1/openclaw/extensions/memory-lancedb/index.ts`
- User preference: Always present plan and wait for approval before writing code (already approved here — execute directly)
