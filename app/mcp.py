"""MCP (Model Context Protocol) server — all agents connect here."""

import asyncio
import json
import logging
import time as _time
from fastapi import APIRouter, Request, HTTPException
from app.config import settings
from fastapi.responses import StreamingResponse

log = logging.getLogger("nexus.mcp")

mcp_router = APIRouter()

TOOLS = [
    {
        "name": "memory_save",
        "description": "Save a memory. Auto-classifies type (world / experience / observation / preference), extracts entities, generates embeddings. Shared across all agents on the network.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "What to remember"},
                "agent_id": {"type": "string", "default": "default"},
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "tags": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_recall",
        "description": "Search all memories using 4-way parallel recall: semantic vector + lexical BM25 + entity graph + temporal recency. Results fused with Reciprocal Rank Fusion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "memory_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by type: world, experience, observation, preference",
                },
                "search_modes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Modes to use: vector, lexical, graph, temporal",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_reflect",
        "description": "Deterministic synthesis over retrieved memories. Returns a direct evidence summary, memory mix, and cautions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "agent_id": {"type": "string"},
                "context": {"type": "string"},
                "depth": {"type": "string", "enum": ["low", "mid", "high"], "default": "mid"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "agent_context",
        "description": "Get everything known about an agent: stored representation, recent memories, extracted conclusions, and entity count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "tokens": {"type": "integer", "default": 2000, "description": "Token budget for context"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "agent_learn",
        "description": "Teach an agent something new. Saves immediately with embedding + async deterministic indexing/extraction where available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "content": {"type": "string"},
                "importance": {"type": "number", "default": 0.5},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["agent_id", "content"],
        },
    },
    {
        "name": "nexus_status",
        "description": "Check health of Nexus and all core components (postgres, redis, embeddings, direct agent API mode).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "memory_save_lesson",
        "description": "WHEN TO USE: After making a mistake, receiving a correction, or learning something that prevents future errors. Saves a high-importance lesson memory (importance=0.9 auto-set, type=lesson). These are never decayed by consolidation and always loaded first in context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The lesson learned (e.g. 'I was wrong about X — the correct answer is Y because Z')"},
                "agent_id": {"type": "string", "default": "default"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_save_global",
        "description": "WHEN TO USE: To share important knowledge with ALL agents on all devices. Saves to the 'global' shared memory pool, visible to every agent during recall. Use for facts, patterns, or context that should be universally known.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "memory_type": {"type": "string", "enum": ["world", "experience", "observation", "preference", "lesson"]},
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_note_to_agent",
        "description": "WHEN TO USE: To leave a note or context for a specific other agent. Saves a memory attributed to that agent, so it appears in their context. Useful for agent-to-agent handoff or cross-agent knowledge transfer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_agent_id": {"type": "string", "description": "The agent to leave the note for"},
                "content": {"type": "string"},
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.65},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["target_agent_id", "content"],
        },
    },
    {
        "name": "memory_synthesize",
        "description": "WHEN TO USE: When you need a comprehensive understanding of a topic based on all stored memories. Returns a deterministic structured knowledge summary built from retrieved evidence. More thorough than recall.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic to synthesize knowledge about"},
                "agent_id": {"type": "string", "description": "Limit to this agent's memories (optional)"},
                "limit": {"type": "integer", "default": 30, "description": "Max memories to draw from"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "agent_represent",
        "description": "WHEN TO USE: After significant new learning or at the start of a session after many memories have accumulated. Rebuilds the agent's stored representation from conclusions and recent memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "memory_confirm",
        "description": "WHEN TO USE: When a recalled memory is verified as correct/helpful. Boosts its trust score so it ranks higher in future recall. Builds memory reliability over time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "ID of the memory to confirm"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_contradict",
        "description": "WHEN TO USE: When a recalled memory is wrong, outdated, or contradicted by new information. Demotes its trust score and importance so it ranks lower in future recall.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "ID of the memory to mark as contradicted"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_profile",
        "description": "WHEN TO USE: At session start, or when you need a complete overview of what is known about an agent/user. Returns ALL stored facts, conclusions, and representation — no search query needed. Cold-start friendly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent to get profile for"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "memory_extract_session",
        "description": "WHEN TO USE: At the end of a conversation session. Extracts durable facts (preferences, decisions, lessons) from the conversation transcript and saves them as memories. Ensures nothing important is lost between sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Conversation messages [{role, content}, ...]",
                },
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "memory_forget_by_query",
        "description": "WHEN TO USE: When the user wants to forget/remove specific memories. Searches for matching memories and deletes them. Supports GDPR/PII compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to find memories to delete"},
                "agent_id": {"type": "string"},
                "max_delete": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "session_start",
        "description": "Start a raw Nexus session archive for this agent/task. Use before substantial work so messages/events can be appended with provenance.",
        "inputSchema": {"type": "object", "properties": {
            "agent_id": {"type": "string", "default": "default"},
            "project_key": {"type": "string"},
            "title": {"type": "string", "maxLength": 500},
            "metadata": {"type": "object"},
        }, "required": []},
    },
    {
        "name": "session_append",
        "description": "Append a raw message/event to a Nexus session archive. Use for user prompts, assistant summaries, tool results, and important events.",
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "role": {"type": "string", "default": "event"},
            "content": {"type": "string"},
            "token_estimate": {"type": "integer", "minimum": 0},
            "metadata": {"type": "object"},
        }, "required": ["session_id", "content"]},
    },
    {
        "name": "session_end",
        "description": "End a Nexus raw session archive. Optionally save a durable session summary memory linked to the session as provenance.",
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "summary": {"type": "string"},
            "durable": {"type": "boolean", "default": False},
            "metadata": {"type": "object"},
        }, "required": ["session_id"]},
    },
    {
        "name": "session_get",
        "description": "Get a Nexus session archive with recent messages.",
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        }, "required": ["session_id"]},
    },
    {
        "name": "session_list",
        "description": "List recent Nexus raw sessions, optionally filtered by agent or project.",
        "inputSchema": {"type": "object", "properties": {
            "agent_id": {"type": "string"},
            "project_key": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        }, "required": []},
    },
    # ── sys_core-compatible sys_core_* tools ─────────────────────────────────
    # These are the same tool names Nexus uses so any Nexus-aware agent
    # works natively against Nexus without reconfiguration.
    # Memory tools (01-09) run natively in Nexus Postgres.
    # Graph tools (10-13) run natively in Nexus Postgres.
    # Filesystem tools (15-23, 28, 31) proxy to the Nexus bridge subprocess.
    {
        "name": "sys_core_01",
        "description": "Search project memory for relevant observations. (Nexus: semantic vector search)",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "maxLength": 2000, "description": "Search query"},
            "project": {"type": "string", "default": "development1", "description": "Project scope (maps to agent)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
        }, "required": ["query"]},
    },
    {
        "name": "sys_core_02",
        "description": "Save observation with auto-conflict-detection. Auto-replaces old conflicting observation if similarity exceeds threshold.",
        "inputSchema": {"type": "object", "properties": {
            "title": {"type": "string", "maxLength": 500},
            "content": {"type": "string", "maxLength": 10000},
            "category": {"type": "string", "enum": ["what-changed","problem-fix","gotcha","decision","trade-off","how-it-works","convention","discovery","tool-pattern"]},
            "project": {"type": "string", "default": "development1"},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.85},
        }, "required": ["title", "content", "category"]},
    },
    {
        "name": "sys_core_03",
        "description": "Save multiple observations at once (up to 10). More efficient than calling sys_core_02 repeatedly.",
        "inputSchema": {"type": "object", "properties": {
            "items": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
                "title": {"type": "string", "maxLength": 500},
                "content": {"type": "string", "maxLength": 10000},
                "category": {"type": "string", "enum": ["what-changed","problem-fix","gotcha","decision","trade-off","how-it-works","convention","discovery","tool-pattern"]},
            }, "required": ["title", "content", "category"]}},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["items"]},
    },
    {
        "name": "sys_core_04",
        "description": "Delete an observation by ID. Use when memory is wrong or outdated.",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Memory UUID to delete"},
        }, "required": ["id"]},
    },
    {
        "name": "sys_core_05",
        "description": "Full-text keyword search across all observations.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "maxLength": 2000},
            "project": {"type": "string", "default": "development1"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
        }, "required": ["query"]},
    },
    {
        "name": "sys_core_06",
        "description": "Compress old, low-value observations to save space and improve search quality. Triggers Nexus consolidation.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_07",
        "description": "Get observation counts, session stats, and basic analytics for the current project.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_08",
        "description": "Get all known gotchas and warnings for this project. Critical things that could cause bugs if forgotten.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_09",
        "description": "Get project conventions, architectural decisions, and patterns.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_10",
        "description": "Create multiple new entities in the knowledge graph. Ignores entities with existing names.",
        "inputSchema": {"type": "object", "properties": {
            "entities": {"type": "array", "maxItems": 100, "items": {"type": "object", "properties": {
                "name": {"type": "string", "maxLength": 500},
                "entityType": {"type": "string", "maxLength": 200},
                "observations": {"type": "array", "items": {"type": "string"}},
            }, "required": ["name", "entityType", "observations"]}},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["entities"]},
    },
    {
        "name": "sys_core_11",
        "description": "Create multiple new relations between entities. Skips duplicate relations.",
        "inputSchema": {"type": "object", "properties": {
            "relations": {"type": "array", "maxItems": 200, "items": {"type": "object", "properties": {
                "from": {"type": "string", "maxLength": 500},
                "to": {"type": "string", "maxLength": 500},
                "relationType": {"type": "string", "maxLength": 200},
            }, "required": ["from", "to", "relationType"]}},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["relations"]},
    },
    {
        "name": "sys_core_12",
        "description": "Retrieve specific Knowledge Graph nodes by name.",
        "inputSchema": {"type": "object", "properties": {
            "names": {"type": "array", "maxItems": 50, "items": {"type": "string", "maxLength": 500}},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["names"]},
    },
    {
        "name": "sys_core_13",
        "description": "Given changed files, find all entities that depend on them (blast radius). Returns impact summary.",
        "inputSchema": {"type": "object", "properties": {
            "files": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
            "max_depth": {"type": "number", "minimum": 1, "maximum": 5, "default": 2},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["files"]},
    },
    {
        "name": "sys_core_14",
        "description": "Get the current active project context — recent memories, entities, representation, and session info.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
            "active_files": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        }},
    },
    {
        "name": "sys_core_15",
        "description": "Replace an entire function, class, or object block in a file using structural bracket matching. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "filePath": {"type": "string", "maxLength": 1000},
            "signature": {"type": "string", "maxLength": 500},
            "newContent": {"type": "string", "maxLength": 500000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["filePath", "signature", "newContent"]},
    },
    {
        "name": "sys_core_16",
        "description": "Get real-time compiler and linter errors (diagnostics) for the workspace. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_17",
        "description": "Get a unified git diff of all uncommitted changes in the workspace. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "dirPath": {"type": "string", "maxLength": 1000, "description": "Absolute path to workspace directory"},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["dirPath"]},
    },
    {
        "name": "sys_core_18",
        "description": "Create a custom skill with rules that agents auto-receive when working on matching files. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "maxLength": 100, "pattern": "^[a-z0-9-]+$"},
            "description": {"type": "string", "maxLength": 500},
            "rules": {"type": "array", "maxItems": 50, "items": {"type": "string"}},
            "trigger_globs": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["name", "description", "rules", "trigger_globs"]},
    },
    {
        "name": "sys_core_19",
        "description": "Execute a dry-run/compilation check in a shadow copy of the workspace before applying changes. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "files_to_modify": {"type": "array", "maxItems": 50, "items": {"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"},
            }, "required": ["path", "content"]}},
            "command": {"type": "string", "maxLength": 500},
            "project_dir": {"type": "string", "maxLength": 1000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["files_to_modify", "command", "project_dir"]},
    },
    {
        "name": "sys_core_20",
        "description": "Read a specific line range from a file. Preserves context window by not reading entire files. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "maxLength": 1000},
            "start_line": {"type": "integer", "minimum": 0},
            "end_line": {"type": "integer", "minimum": 0},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["path", "start_line", "end_line"]},
    },
    {
        "name": "sys_core_21",
        "description": "Resolve a library name to a Context7-compatible library ID for documentation queries. [Proxied via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "libraryName": {"type": "string", "maxLength": 200},
            "query": {"type": "string", "maxLength": 2000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["libraryName", "query"]},
    },
    {
        "name": "sys_core_22",
        "description": "Fetch up-to-date documentation and code snippets from Context7. Requires libraryId from sys_core_21. [Proxied via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "libraryId": {"type": "string", "maxLength": 200},
            "query": {"type": "string", "maxLength": 2000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["libraryId", "query"]},
    },
    {
        "name": "sys_core_23",
        "description": "Semantic codebase search — find functions/classes by meaning using offline ONNX embeddings. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "maxLength": 2000},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["query"]},
    },
    {
        "name": "sys_core_24",
        "description": "Create a backup/export of the current project memory (observations) as a JSON snapshot.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_25",
        "description": "Restore project memory from a previously exported backup. Merges into existing memories.",
        "inputSchema": {"type": "object", "properties": {
            "backup_key": {"type": "string", "description": "Backup key returned by sys_core_24"},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["backup_key"]},
    },
    {
        "name": "sys_core_26",
        "description": "List available memory backups/exports for a project.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_27",
        "description": "Check current memory health and scan progress for this project.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_28",
        "description": "Search for a regex pattern across project files. Returns matches with file paths and line numbers. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "pattern": {"type": "string", "maxLength": 500},
            "dir": {"type": "string", "maxLength": 1000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["pattern"]},
    },
    {
        "name": "sys_core_29",
        "description": "Save the current task state/checklist to Redis. Survives context wipes — call sys_core_30 to recover.",
        "inputSchema": {"type": "object", "properties": {
            "state": {"type": "string", "description": "Task state or checklist markdown"},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["state"]},
    },
    {
        "name": "sys_core_30",
        "description": "Retrieve the last saved task state/checklist for this project. Call at startup to recover context.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "default": "development1"},
        }},
    },
    {
        "name": "sys_core_31",
        "description": "Extract structural AST skeleton of a file (classes, methods, types) without implementation details. [Runs on host via bridge]",
        "inputSchema": {"type": "object", "properties": {
            "filePath": {"type": "string", "maxLength": 1000},
            "project": {"type": "string", "default": "development1"},
        }, "required": ["filePath"]},
    },

    # ── Synapse-compat tools ──────────────────────────────────────────────────
    {
        "name": "register_project",
        "description": "Register or update a project/workspace for shared memory routing.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string"},
            "name": {"type": "string"},
            "root": {"type": "string"},
        }, "required": ["project_key"]},
    },
    {
        "name": "remember",
        "description": "Store a project-scoped memory. Use kind for categorization.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "kind": {"type": "string", "default": "note"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "importance": {"type": "number", "minimum": 1, "maximum": 5, "default": 3},
            "source": {"type": "string", "default": "agent"},
        }, "required": ["content"]},
    },
    {
        "name": "recall",
        "description": "Search project memory by kind/tags/keyword.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "query": {"type": "string"},
            "kind": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "default": 10},
        }},
    },
    {
        "name": "ingest_file",
        "description": "Index a local file into shared project context.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "path": {"type": "string"},
        }, "required": ["path"]},
    },
    {
        "name": "search_files",
        "description": "Search indexed files by query or language.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "query": {"type": "string"},
            "language": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        }},
    },
    {
        "name": "project_context",
        "description": "Combined context: project info + memories + indexed files.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 12},
        }},
    },
    {
        "name": "list_projects",
        "description": "List all registered projects.",
        "inputSchema": {"type": "object", "properties": {
            "limit": {"type": "integer", "default": 50},
        }},
    },
    {
        "name": "recent_activity",
        "description": "Recent events for a project.",
        "inputSchema": {"type": "object", "properties": {
            "project_key": {"type": "string", "default": "default"},
            "limit": {"type": "integer", "default": 20},
        }},
    },
    {
        "name": "synapse_compat_health",
        "description": "Health check for synapse-compat tables.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # ---- Living Mind tools (adopted) ---------------------------------------
    # The Mind is a reasoning layer on top of the memory store.  These
    # tools let an agent converse with the Mind rather than query a
    # database — the Mind retrieves memories, reasons about them,
    # forms opinions, and proactively surfaces context.
    {
        "name": "mind_think",
        "description": (
            "Ask the living mind a question and get a reasoned response. "
            "The mind retrieves relevant memories, reasons about them, "
            "forms opinions, and proactively surfaces context. Use this "
            "when you need context, an explanation, or a thoughtful opinion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the mind."},
                "mind_id": {"type": "string", "default": "default"},
                "context": {"type": "object", "description": "Optional context (agent_id, etc.)."},
                "reasoning_depth": {"type": "string", "enum": ["fast", "standard", "deep"]},
            },
            "required": ["question"],
        },
    },
    {
        "name": "mind_reflect",
        "description": "Ask the mind to reflect deeply on a topic. Synthesises many memories into a single coherent narrative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
                "depth": {"type": "string", "enum": ["low", "mid", "high"], "default": "mid"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "mind_start_conversation",
        "description": "Start a multi-turn conversation with the mind. Returns a conversation_id for subsequent turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "mind_conversation_turn",
        "description": "Send a turn in an ongoing conversation with the mind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "message": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["conversation_id", "message"],
        },
    },
    {
        "name": "mind_end_conversation",
        "description": "End a conversation with the mind and extract learnings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string"},
                "mind_id": {"type": "string", "default": "default"},
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "mind_get_identity",
        "description": "Get the mind's current self-model — core traits, learned patterns, capabilities, and limitations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
            },
        },
    },
    {
        "name": "mind_get_opinions",
        "description": "Get the mind's opinions on topics. Returns stance, strength, and evidence count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
                "topic": {"type": "string"},
            },
        },
    },
    {
        "name": "mind_get_proactive",
        "description": "Get proactive context the mind thinks is relevant — unfinished promises, recent related work, contradictions, patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mind_id": {"type": "string", "default": "default"},
                "agent_id": {"type": "string", "default": "agent"},
                "question": {"type": "string"},
            },
        },
    },
]

async def _dispatch(tool: str, args: dict, request: Request) -> str:
    import httpx
    # Internal loopback, NOT request.base_url: every MCP tool below makes a
    # same-process self-call back into this API. Building that URL from the
    # incoming request's Host meant any client reaching this server via its
    # Tailscale/LAN IP (i.e. every remote agent) made the container hairpin
    # back out through the host's external IP, which Docker's default bridge
    # networking does not route -- every tool call hung/failed for anyone
    # not connecting from localhost.
    base = f"http://127.0.0.1:{settings.nexus_port}"
    headers = {"Content-Type": "application/json"}
    if auth := request.headers.get("Authorization"):
        headers["Authorization"] = auth

    async with httpx.AsyncClient(timeout=300.0) as client:
        if tool == "memory_save":
            r = await client.post(f"{base}/v1/memory/save", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Saved {d['id'][:8]}... | type: {d['classified_type']} | extraction queued: {d['extraction_queued']}"

        elif tool == "memory_recall":
            r = await client.post(f"{base}/v1/memory/recall", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["results"]:
                return "No memories found."
            lines = [f"Found {d['total']} memories (modes: {', '.join(d['modes_used'])}):\n"]
            for i, m in enumerate(d["results"], 1):
                star = "★" if len(m["matched_by"]) > 1 else " "
                lines.append(f"{i}.{star}[{m['memory_type']}] score={m['score']:.3f}  {m['content'][:400]}")
            return "\n".join(lines)

        elif tool == "memory_reflect":
            r = await client.post(f"{base}/v1/memory/reflect", json=args, headers=headers)
            r.raise_for_status()
            return r.json()["reflection"]

        elif tool == "agent_context":
            agent_id = args.pop("agent_id")
            r = await client.get(f"{base}/v1/agents/{agent_id}/context", params=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            lines = [f"Agent '{agent_id}':"]
            if d.get("representation"):
                lines.append(f"\n{d['representation']}")
            if d.get("conclusions"):
                lines.append(f"\nConclusions ({len(d['conclusions'])}):")
                for c in d["conclusions"][:5]:
                    lines.append(f"  - {c}")
            if d.get("recent_memories"):
                lines.append(f"\nMemories ({len(d['recent_memories'])}):")
                for m in d["recent_memories"][:5]:
                    lines.append(f"  - [{m['memory_type']}] {m['content'][:200]}")
            lines.append(f"\nKnown entities: {d.get('entity_count', 0)}")
            return "\n".join(lines)

        elif tool == "agent_learn":
            agent_id = args.pop("agent_id")
            r = await client.post(f"{base}/v1/agents/{agent_id}/learn", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Learned for '{agent_id}': {d['id'][:8]}... | type: {d['classified_type']}"

        elif tool == "nexus_status":
            r = await client.get(f"{base}/health", headers=headers)
            r.raise_for_status()
            d = r.json()
            lines = [f"Nexus {'healthy' if d['healthy'] else 'DEGRADED'} v{d['version']}:"]
            for k, v in d.get("components", {}).items():
                lines.append(f"  {'✅' if v else '❌'} {k}")
            return "\n".join(lines)

        elif tool == "memory_save_lesson":
            payload = {
                "content": args.get("content", ""),
                "agent_id": args.get("agent_id", "default"),
                "memory_type": "lesson",
                "importance": 0.9,
                "tags": args.get("tags", []),
            }
            r = await client.post(f"{base}/v1/memory/save", json=payload, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Lesson saved {d['id'][:8]}... | Will persist through consolidation | extraction queued: {d['extraction_queued']}"

        elif tool == "memory_save_global":
            payload = {
                "content": args.get("content", ""),
                "agent_id": "global",
                "memory_type": args.get("memory_type"),
                "importance": args.get("importance", 0.6),
                "tags": args.get("tags", []),
            }
            r = await client.post(f"{base}/v1/memory/save", json=payload, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Global memory saved {d['id'][:8]}... | visible to all agents | type: {d['classified_type']}"

        elif tool == "memory_note_to_agent":
            target = args.get("target_agent_id", "")
            payload = {
                "content": args.get("content", ""),
                "agent_id": target,
                "memory_type": "observation",
                "importance": args.get("importance", 0.65),
                "tags": args.get("tags", []) + ["agent-note"],
            }
            r = await client.post(f"{base}/v1/memory/save", json=payload, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Note saved for agent '{target}': {d['id'][:8]}..."

        elif tool == "memory_synthesize":
            topic = args.get("topic", "")
            r = await client.post(f"{base}/v1/memory/reflect", json={
                "query": topic,
                "agent_id": args.get("agent_id"),
                "depth": "high",
                "context": "Please synthesize all knowledge on this topic comprehensively, generating a structured knowledge document with key facts, relationships, patterns, and any gaps or contradictions.",
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            reflection = d.get("reflection", "")
            return f"Knowledge synthesis on '{topic}':\n\n{reflection}"

        # ── sys_core_* tools (sys_core-compatible) ───────────────────────────

        elif tool == "sys_core_01":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/memory/recall", json={
                "query": args.get("query", ""),
                "agent_id": project,
                "limit": args.get("limit", 10),
                "search_modes": ["vector"],
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["results"]:
                return "No memories found."
            lines = [f"Project '{project}' — {d['total']} results:\n"]
            for i, m in enumerate(d["results"], 1):
                cat = (m.get("metadata") or {}).get("category", m["memory_type"])
                lines.append(f"{i}. [{cat}] score={m['score']:.3f}  {m['content'][:400]}")
            return "\n".join(lines)

        elif tool == "sys_core_02":
            project = args.get("project", "development1")
            title = args.get("title", "")
            content = args.get("content", "")
            category = args.get("category", "how-it-works")
            threshold = float(args.get("threshold", 0.85))
            full = f"{title}: {content}" if title else content
            _CATEGORY_TO_TYPE = {
                "gotcha": "lesson", "problem-fix": "lesson",
                "decision": "world", "trade-off": "world",
                "how-it-works": "world", "convention": "world",
                "what-changed": "experience", "discovery": "experience", "tool-pattern": "experience",
            }
            memory_type = _CATEGORY_TO_TYPE.get(category, "observation")
            # Conflict detection: find similar existing memory
            r_search = await client.post(f"{base}/v1/memory/recall", json={
                "query": full[:500], "agent_id": project, "limit": 3, "search_modes": ["vector"],
            }, headers=headers)
            if r_search.status_code == 200:
                for m in r_search.json().get("results", []):
                    if m.get("score", 0) >= threshold:
                        await client.delete(f"{base}/v1/memory/{m['id']}", headers=headers)
                        break
            r = await client.post(f"{base}/v1/memory/save", json={
                "content": full[:50_000], "agent_id": project,
                "memory_type": memory_type, "importance": 0.7,
                "tags": [category, f"project:{project}"],
                "metadata": {"category": category, "title": title, "project": project},
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Saved {d['id'][:8]}... | [{category}] | project:{project}"

        elif tool == "sys_core_03":
            project = args.get("project", "development1")
            _CATEGORY_TO_TYPE = {
                "gotcha": "lesson", "problem-fix": "lesson",
                "decision": "world", "trade-off": "world",
                "how-it-works": "world", "convention": "world",
                "what-changed": "experience", "discovery": "experience", "tool-pattern": "experience",
            }
            saved, errors = 0, 0
            for item in args.get("items", []):
                cat = item.get("category", "how-it-works")
                title = item.get("title", "")
                content = item.get("content", "")
                full = f"{title}: {content}" if title else content
                try:
                    r = await client.post(f"{base}/v1/memory/save", json={
                        "content": full[:50_000], "agent_id": project,
                        "memory_type": _CATEGORY_TO_TYPE.get(cat, "observation"),
                        "importance": 0.7,
                        "tags": [cat, f"project:{project}"],
                        "metadata": {"category": cat, "title": title, "project": project},
                    }, headers=headers)
                    r.raise_for_status()
                    saved += 1
                except Exception:
                    errors += 1
            return f"Batch save: {saved} saved, {errors} errors | project:{project}"

        elif tool == "sys_core_04":
            memory_id = str(args.get("id", ""))
            r = await client.delete(f"{base}/v1/memory/{memory_id}", headers=headers)
            if r.status_code == 404:
                return f"Memory {memory_id} not found."
            r.raise_for_status()
            return f"Deleted memory {memory_id}"

        elif tool == "sys_core_05":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/memory/recall", json={
                "query": args.get("query", ""),
                "agent_id": project,
                "limit": args.get("limit", 10),
                "search_modes": ["lexical"],
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["results"]:
                return "No memories found."
            lines = [f"Fulltext '{args['query']}' — {d['total']} results:\n"]
            for i, m in enumerate(d["results"], 1):
                cat = (m.get("metadata") or {}).get("category", m["memory_type"])
                lines.append(f"{i}. [{cat}] {m['content'][:400]}")
            return "\n".join(lines)

        elif tool == "sys_core_06":
            r = await client.post(f"{base}/v1/admin/consolidate", json={}, headers=headers)
            r.raise_for_status()
            return f"Consolidation triggered: {r.json()}"

        elif tool == "sys_core_07":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/memory/recall", json={
                "query": " ", "agent_id": project, "limit": 1, "search_modes": ["lexical"],
            }, headers=headers)
            total = r.json().get("total", "?") if r.status_code == 200 else "?"
            r2 = await client.get(f"{base}/health", headers=headers)
            h = r2.json() if r2.status_code == 200 else {}
            return (f"Project '{project}': ~{total} observations\n"
                    f"Nexus health: {'healthy' if h.get('healthy') else 'degraded'} | "
                    f"db: {'ok' if h.get('components', {}).get('database') else 'error'} | "
                    f"redis: {'ok' if h.get('components', {}).get('redis') else 'error'}")

        elif tool == "sys_core_08":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/memory/recall", json={
                "query": "gotcha warning trap critical bug pitfall",
                "agent_id": project, "limit": 50,
                "search_modes": ["vector", "lexical"],
                "memory_types": ["lesson"],
            }, headers=headers)
            r.raise_for_status()
            results = [m for m in r.json()["results"]
                       if (m.get("metadata") or {}).get("category") == "gotcha"
                       or "gotcha" in (m.get("tags") or [])]
            if not results:
                return f"No gotchas recorded for project '{project}'."
            lines = [f"Gotchas for '{project}' ({len(results)}):\n"]
            for m in results:
                title = (m.get("metadata") or {}).get("title", "")
                lines.append(f"  ⚠ {title or m['content'][:200]}")
            return "\n".join(lines)

        elif tool == "sys_core_09":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/memory/recall", json={
                "query": "convention decision architecture pattern rule standard",
                "agent_id": project, "limit": 50,
                "search_modes": ["vector", "lexical"],
                "memory_types": ["world"],
            }, headers=headers)
            r.raise_for_status()
            _conv_cats = {"convention", "decision", "trade-off", "how-it-works"}
            results = [m for m in r.json()["results"]
                       if (m.get("metadata") or {}).get("category") in _conv_cats]
            if not results:
                return f"No conventions/decisions recorded for project '{project}'."
            lines = [f"Conventions for '{project}' ({len(results)}):\n"]
            for m in results:
                cat = (m.get("metadata") or {}).get("category", "")
                title = (m.get("metadata") or {}).get("title", "")
                lines.append(f"  [{cat}] {title or m['content'][:200]}")
            return "\n".join(lines)

        elif tool == "sys_core_10":
            project = args.get("project", "development1")
            entities = args.get("entities", [])
            r = await client.post(f"{base}/v1/agents/{project}/entities",
                                  json={"entities": entities}, headers=headers)
            r.raise_for_status()
            d = r.json()
            # Also save entity observations as memories
            for ent in entities:
                for obs in ent.get("observations", [])[:3]:
                    await client.post(f"{base}/v1/memory/save", json={
                        "content": f"[{ent['name']} ({ent['entityType']})]: {obs}",
                        "agent_id": project, "memory_type": "observation", "importance": 0.6,
                        "tags": ["entity", ent["entityType"], f"project:{project}"],
                        "metadata": {"entity": ent["name"], "category": "how-it-works", "project": project},
                    }, headers=headers)
            return f"Created {d['created']} entities in project '{project}'"

        elif tool == "sys_core_11":
            project = args.get("project", "development1")
            r = await client.post(f"{base}/v1/agents/{project}/relations",
                                  json={"relations": args.get("relations", [])}, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Created {d['created']} relations in project '{project}'"

        elif tool == "sys_core_12":
            project = args.get("project", "development1")
            names = args.get("names", [])
            r = await client.get(f"{base}/v1/agents/{project}/entities",
                                 params={"names": ",".join(names)}, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["entities"]:
                return f"No entities found for names: {names}"
            lines = [f"Entities in '{project}':"]
            for e in d["entities"]:
                rels = ", ".join(e.get("relations", [])[:5])
                lines.append(f"  {e['name']} [{e['entityType']}] → {rels or '(no relations)'}")
            return "\n".join(lines)

        elif tool == "sys_core_13":
            project = args.get("project", "development1")
            files = args.get("files", [])
            r = await client.get(f"{base}/v1/agents/{project}/blast-radius",
                                 params={"files": ",".join(files), "max_depth": args.get("max_depth", 2)},
                                 headers=headers)
            r.raise_for_status()
            d = r.json()
            impacted = d.get("impacted", [])
            if not impacted:
                return f"No impacted entities found for: {files}"
            lines = [f"Blast radius for {files} (depth {d['depth_reached']}): {len(impacted)} impacted"]
            for e in impacted[:20]:
                lines.append(f"  - {e['name']}")
            return "\n".join(lines)

        elif tool == "sys_core_14":
            project = args.get("project", "development1")
            r = await client.get(f"{base}/v1/agents/{project}/context", headers=headers)
            r.raise_for_status()
            d = r.json()
            lines = [f"Project '{project}' context:"]
            if d.get("representation"):
                lines.append(f"\n{d['representation']}")
            if d.get("conclusions"):
                lines.append(f"\nConclusions ({len(d['conclusions'])}):")
                for c in d["conclusions"][:5]:
                    lines.append(f"  - {c}")
            if d.get("recent_memories"):
                lines.append(f"\nRecent observations ({len(d['recent_memories'])}):")
                for m in d["recent_memories"][:8]:
                    cat = (m.get("metadata") or {}).get("category", m.get("memory_type", ""))
                    title = (m.get("metadata") or {}).get("title", "")
                    lines.append(f"  [{cat}] {title or m['content'][:150]}")
            return "\n".join(lines)

        elif tool in ("sys_core_15", "sys_core_16", "sys_core_17", "sys_core_18",
                      "sys_core_19", "sys_core_20", "sys_core_21", "sys_core_22",
                      "sys_core_23", "sys_core_28", "sys_core_31"):
            # Filesystem/host tools — proxy to Nexus bridge subprocess
            project = args.get("project", "development1")
            bridge_args = {k: v for k, v in args.items() if k != "project"}
            r = await client.post(f"{base}/v1/sys/bridge", json={
                "project": project, "tool": tool, "args": bridge_args,
            }, headers=headers)
            r.raise_for_status()
            result = r.json().get("result", {})
            if isinstance(result, dict) and "text" in result:
                return result["text"]
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2)

        elif tool == "sys_core_24":
            project = args.get("project", "development1")
            r = await client.get(f"{base}/v1/admin/export/{project}", headers=headers)
            r.raise_for_status()
            data = r.text
            # Store in Redis with timestamp key
            key = f"backup:{project}:{int(_time.time())}"
            # We can't directly set Redis from here; store via the bridge taskstate hack
            r2 = await client.put(f"{base}/v1/sys/taskstate/__backup_{project}",
                                  json={"state": key + "|" + data[:100_000]}, headers=headers)
            return f"Backup created: key={key} | {len(data)} chars exported"

        elif tool == "sys_core_25":
            return "Restore: use the /v1/admin/import endpoint with the exported JSONL data."

        elif tool == "sys_core_26":
            project = args.get("project", "development1")
            r = await client.get(f"{base}/v1/sys/taskstate/__backup_{project}", headers=headers)
            if r.status_code == 200:
                state = r.json().get("state", "")
                key = state.split("|")[0] if "|" in state else ""
                return f"Latest backup for '{project}': {key or '(none)'}"
            return f"No backups found for project '{project}'."

        elif tool == "sys_core_27":
            project = args.get("project", "development1")
            r = await client.get(f"{base}/health", headers=headers)
            r.raise_for_status()
            d = r.json()
            r2 = await client.post(f"{base}/v1/memory/recall", json={
                "query": " ", "agent_id": project, "limit": 1, "search_modes": ["lexical"],
            }, headers=headers)
            total = r2.json().get("total", "?") if r2.status_code == 200 else "?"
            return (f"Project '{project}' status:\n"
                    f"  observations: ~{total}\n"
                    f"  nexus: {'healthy' if d['healthy'] else 'DEGRADED'} v{d['version']}\n"
                    f"  components: {d.get('components', {})}")

        elif tool == "sys_core_29":
            project = args.get("project", "development1")
            r = await client.put(f"{base}/v1/sys/taskstate/{project}",
                                 json={"state": args.get("state", "")}, headers=headers)
            r.raise_for_status()
            return f"Task state saved for project '{project}'"

        elif tool == "sys_core_30":
            project = args.get("project", "development1")
            r = await client.get(f"{base}/v1/sys/taskstate/{project}", headers=headers)
            r.raise_for_status()
            d = r.json()
            state = d.get("state", "")
            if not state:
                return f"No task state saved for project '{project}'."
            return f"Task state for '{project}':\n{state}"

        elif tool == "agent_represent":
            agent_id = args.get("agent_id", "")
            r = await client.post(f"{base}/v1/browse/agents/{agent_id}/represent", headers=headers)
            r.raise_for_status()
            d = r.json()
            if d.get("rebuilt") and d.get("representation"):
                return f"Representation rebuilt for '{agent_id}':\n{d['representation']}"
            return f"No representation built for '{agent_id}' — not enough memories yet (need conclusions or experiences)."

        elif tool == "memory_confirm":
            memory_id = args.get("memory_id", "")
            r = await client.post(f"{base}/v1/memory/{memory_id}/confirm", headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Memory {memory_id[:8]}... confirmed (count: {d.get('confirmed_count', 0)}). Trust score boosted."

        elif tool == "memory_contradict":
            memory_id = args.get("memory_id", "")
            r = await client.post(f"{base}/v1/memory/{memory_id}/contradict", headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Memory {memory_id[:8]}... marked contradicted (count: {d.get('contradicted_count', 0)}). Trust score demoted."

        elif tool == "memory_profile":
            agent_id = args.get("agent_id", "default")
            r = await client.get(f"{base}/v1/memory/profile/{agent_id}", headers=headers)
            r.raise_for_status()
            d = r.json()
            lines = [f"Profile for '{agent_id}' ({d.get('total', 0)} memories):"]
            if d.get("representation"):
                lines.append(f"\n{d['representation']}")
            if d.get("conclusions"):
                lines.append(f"\nConclusions ({len(d['conclusions'])}):")
                for c in d["conclusions"][:10]:
                    lines.append(f"  - {c}")
            if d.get("by_type"):
                lines.append(f"\nBy type: {d['by_type']}")
            if d.get("memories"):
                lines.append(f"\nTop memories:")
                for m in d["memories"][:15]:
                    trust = ""
                    if m.get("confirmed") or m.get("contradicted"):
                        trust = f" [✓{m['confirmed']} ⚠{m['contradicted']}]"
                    lines.append(f"  [{m['memory_type']}] imp={m['importance']:.2f}{trust}  {m['content'][:200]}")
            return "\n".join(lines)

        elif tool == "session_start":
            r = await client.post(f"{base}/v1/sessions/start", json={
                "agent_id": args.get("agent_id", "default"),
                "project_key": args.get("project_key"),
                "title": args.get("title"),
                "metadata": args.get("metadata", {}),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Session started: {d['session_id']} agent={d['agent_id']} started_at={d['started_at']}"

        elif tool == "session_append":
            session_id = args.get("session_id", "")
            r = await client.post(f"{base}/v1/sessions/{session_id}/messages", json={
                "role": args.get("role", "event"),
                "content": args.get("content", ""),
                "token_estimate": args.get("token_estimate"),
                "metadata": args.get("metadata", {}),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Session message appended: {d['message_id']} tokens≈{d['token_estimate']}"

        elif tool == "session_end":
            session_id = args.get("session_id", "")
            r = await client.post(f"{base}/v1/sessions/{session_id}/end", json={
                "summary": args.get("summary"),
                "durable": args.get("durable", False),
                "metadata": args.get("metadata", {}),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            msg = f"Session ended: {d['session_id']}"
            if d.get("memory_id"):
                msg += f"; durable summary memory={d['memory_id']}"
            return msg

        elif tool == "session_get":
            session_id = args.get("session_id", "")
            r = await client.get(f"{base}/v1/sessions/{session_id}", params={"limit": args.get("limit", 200)}, headers=headers)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

        elif tool == "session_list":
            params = {"limit": args.get("limit", 50)}
            if args.get("agent_id"):
                params["agent_id"] = args.get("agent_id")
            if args.get("project_key"):
                params["project_key"] = args.get("project_key")
            r = await client.get(f"{base}/v1/sessions", params=params, headers=headers)
            r.raise_for_status()
            sessions = r.json()
            if not sessions:
                return "No sessions found."
            lines = [f"Sessions ({len(sessions)}):"]
            for s in sessions:
                ended = s.get("ended_at") or "active"
                lines.append(f"  {s['id']} agent={s['agent_id']} project={s.get('project_key') or '-'} messages={s.get('message_count', 0)} ended={ended}")
            return "\n".join(lines)

        elif tool == "memory_extract_session":
            from app.memory.session import extract_session_facts
            messages = args.get("messages", [])
            agent_id = args.get("agent_id", "default")
            session_id = args.get("session_id")
            source_message_ids = []
            if session_id and not messages:
                sr = await client.get(f"{base}/v1/sessions/{session_id}", params={"limit": args.get("limit", 200)}, headers=headers)
                sr.raise_for_status()
                sd = sr.json()
                messages = sd.get("messages", [])
                agent_id = args.get("agent_id") or sd.get("agent_id", agent_id)
                source_message_ids = [m.get("id") for m in messages if m.get("id")]
            else:
                source_message_ids = [m.get("id") for m in messages if isinstance(m, dict) and m.get("id")]
            extractions = await extract_session_facts(messages, agent_id)
            if not extractions:
                return "No durable facts extracted from this session."
            saved = 0
            linked = 0
            for ext in extractions:
                try:
                    r = await client.post(f"{base}/v1/memory/save", json={
                        "content": ext["content"],
                        "agent_id": agent_id,
                        "memory_type": ext.get("type", "observation"),
                        "importance": ext.get("importance", 0.6),
                        "tags": ["session-extract"],
                        "metadata": {"source": "session-extraction", "session_id": session_id, "source_message_ids": source_message_ids[:50]},
                    }, headers=headers)
                    r.raise_for_status()
                    saved_memory = r.json()
                    memory_id = saved_memory.get("id")
                    saved += 1
                    for mid in source_message_ids[:50]:
                        try:
                            lr = await client.post(f"{base}/v1/sessions/sources/link", json={
                                "memory_id": memory_id,
                                "source_kind": "message",
                                "source_id": mid,
                                "metadata": {"session_id": session_id, "extract_type": ext.get("type", "observation")},
                            }, headers=headers)
                            if lr.status_code < 400:
                                linked += 1
                        except Exception:
                            pass
                except Exception:
                    pass
            lines = [f"Extracted and saved {saved} facts from session. Provenance links: {linked}"]
            for ext in extractions:
                lines.append(f"  [{ext.get('type', '?')}] {ext['content'][:200]}")
            return "\n".join(lines)

        elif tool == "memory_forget_by_query":
            query = args.get("query", "")
            agent_id = args.get("agent_id")
            max_delete = min(int(args.get("max_delete", 5)), 20)
            recall_args = {"query": query, "limit": max_delete, "search_modes": ["vector", "lexical"]}
            if agent_id:
                recall_args["agent_id"] = agent_id
            r = await client.post(f"{base}/v1/memory/recall", json=recall_args, headers=headers)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return f"No memories found matching '{query}'."
            deleted = 0
            for m in results:
                try:
                    dr = await client.delete(f"{base}/v1/memory/{m['id']}", headers=headers)
                    if dr.status_code < 300:
                        deleted += 1
                except Exception:
                    pass
            return f"Deleted {deleted} of {len(results)} memories matching '{query}'."

        
        elif tool == "register_project":
            r = await client.post(f"{base}/v1/synapse/projects/register", params={"key": args.get("project_key", ""), "name": args.get("name"), "root": args.get("root")}, headers=headers)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

        elif tool == "remember":
            pk = args.get("project_key", "default")
            r = await client.post(f"{base}/v1/synapse/projects/{pk}/remember", json={
                "kind": args.get("kind", "note"),
                "title": args.get("title", ""),
                "content": args.get("content", ""),
                "source": args.get("source", "agent"),
                "tags": args.get("tags", []),
                "importance": args.get("importance", 3),
            }, headers=headers)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

        elif tool == "recall":
            pk = args.get("project_key", "default")
            r = await client.post(f"{base}/v1/synapse/projects/{pk}/recall", json={
                "query": args.get("query", ""),
                "kind": args.get("kind"),
                "tags": args.get("tags"),
                "limit": args.get("limit", 10),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["memories"]:
                return "No memories found."
            lines = [f"Project '{pk}' - {d['count']} memories:"]
            for i, m in enumerate(d["memories"], 1):
                lines.append(f"{i}. [{m['kind']}] imp={m['importance']}  {m['content'][:300]}")
            return "\n".join(lines)

        elif tool == "ingest_file":
            pk = args.get("project_key", "default")
            r = await client.post(f"{base}/v1/synapse/projects/{pk}/files/ingest", params={"path": args["path"]}, headers=headers)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

        elif tool == "search_files":
            pk = args.get("project_key", "default")
            r = await client.post(f"{base}/v1/synapse/projects/{pk}/files/search", json={
                "query": args.get("query", ""),
                "language": args.get("language"),
                "limit": args.get("limit", 20),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["files"]:
                return "No files found."
            lines = [f"Project '{pk}' - {d['count']} files:"]
            for f_obj in d["files"]:
                lang = f_obj.get("language", "?")
                lines.append(f"  {f_obj['path']} [{lang}] sha={f_obj['sha256'][:12]}...")
            return "\n".join(lines)

        elif tool == "project_context":
            pk = args.get("project_key", "default")
            r = await client.get(f"{base}/v1/synapse/projects/{pk}/context", params={
                "query": args.get("query", ""),
                "limit": args.get("limit", 12),
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            lines = [f"Project '{pk}' context:"]
            proj = d.get("project", {})
            lines.append(f"  Name: {proj.get('name', proj.get('key', '?'))}")
            memories = d.get("memories", [])
            files = d.get("files", [])
            lines.append(f"  Memories: {len(memories)}  Files: {len(files)}")
            if memories:
                lines.append("  Top memories:")
                for m in memories[:5]:
                    lines.append(f"    [{m.get('kind', m.get('memory_type', '?'))}] {m['content'][:200]}")
            return "\n".join(lines)

        elif tool == "list_projects":
            r = await client.get(f"{base}/v1/synapse/projects", params={"limit": args.get("limit", 50)}, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["projects"]:
                return "No projects registered."
            lines = [f"Projects ({d['count']}):"]
            for p in d["projects"]:
                lines.append(f"  {p['key']} - {p['name']} (root: {p.get('root', '-')})")
            return "\n".join(lines)

        elif tool == "recent_activity":
            pk = args.get("project_key", "default")
            r = await client.get(f"{base}/v1/synapse/projects/{pk}/events", params={"limit": args.get("limit", 20)}, headers=headers)
            r.raise_for_status()
            d = r.json()
            if not d["events"]:
                return "No recent activity."
            lines = [f"Activity for '{pk}' ({d['count']}):"]
            for e in d["events"][:10]:
                lines.append(f"  [{e['action']}] {e['actor']}: {e['detail'][:100]}")
            return "\n".join(lines)

        elif tool == "synapse_compat_health":
            r = await client.get(f"{base}/v1/synapse/health/synapse", headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Synapse compat health: projects={d['projects']} files={d['files']} events={d['events']}"

        # ---- Living Mind (adopted) ------------------------------------
        elif tool == "mind_think":
            r = await client.post(f"{base}/v1/mind/think", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            parts = []
            if d.get("answer"):
                parts.append(d["answer"])
            if d.get("clarifying_question"):
                parts.append(f"Question back: {d['clarifying_question']}")
            if d.get("proactive_context"):
                parts.append("\nProactive context:")
                for item in d["proactive_context"][:3]:
                    parts.append(f"  - {item['content']} (relevance {item['relevance']:.2f})")
            if d.get("opinions_expressed"):
                parts.append("\nMy take:")
                for op in d["opinions_expressed"]:
                    parts.append(f"  - {op['topic']}: {op['stance']} (strength {op['strength']:.2f})")
            parts.append(f"\nConfidence: {d.get('confidence', 0):.2f} | Memories: {len(d.get('memories_cited', []))}")
            return "\n".join(parts)

        elif tool == "mind_reflect":
            r = await client.post(f"{base}/v1/mind/reflect", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            return d.get("answer") or "No reflection available."

        elif tool == "mind_start_conversation":
            r = await client.post(f"{base}/v1/mind/conversations/start", json=args, headers=headers)
            r.raise_for_status()
            d = r.json()
            return f"Started conversation {d['conversation_id']} with mind '{d['mind_id']}'."

        elif tool == "mind_conversation_turn":
            conv_id = args.pop("conversation_id")
            r = await client.post(
                f"{base}/v1/mind/conversations/{conv_id}/turn",
                json=args, headers=headers,
            )
            r.raise_for_status()
            d = r.json()
            parts = []
            if d.get("answer"):
                parts.append(d["answer"])
            if d.get("clarifying_question"):
                parts.append(f"Question back: {d['clarifying_question']}")
            return "\n".join(parts) if parts else "(no response)"

        elif tool == "mind_end_conversation":
            conv_id = args.pop("conversation_id")
            r = await client.post(
                f"{base}/v1/mind/conversations/{conv_id}/end",
                json=args, headers=headers,
            )
            r.raise_for_status()
            d = r.json()
            insights = d.get("insights", [])
            return (
                f"Conversation ended. {d.get('turn_count', 0)} turns. "
                f"{len(insights)} learnings extracted: {insights}"
            )

        elif tool == "mind_get_identity":
            mid = args.get("mind_id", "default")
            r = await client.get(f"{base}/v1/mind/identity/{mid}", headers=headers)
            r.raise_for_status()
            return r.json().get("description", "No description available.")

        elif tool == "mind_get_opinions":
            mid = args.get("mind_id", "default")
            topic = args.get("topic")
            url = f"{base}/v1/mind/opinions/{mid}"
            if topic:
                url += f"?topic={topic}"
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            d = r.json()
            opinions = d.get("opinions", {})
            if not opinions:
                return "No opinions held yet."
            if not isinstance(opinions, dict):
                return f"Opinion on '{topic}': {opinions}"
            lines = ["Mind's opinions:"]
            for topic_name, op in opinions.items():
                if op is None:
                    continue
                lines.append(f"  - {topic_name}: {op['stance']} (strength {op['strength']:.2f}, {op['evidence_count']} pieces of evidence)")
            return "\n".join(lines)

        elif tool == "mind_get_proactive":
            mid = args.get("mind_id", "default")
            agent_id = args.get("agent_id", "agent")
            question = args.get("question", "What should I know right now?")
            r = await client.post(f"{base}/v1/mind/think", json={
                "mind_id": mid,
                "question": question,
                "context": {"agent_id": agent_id, "proactive_only": True},
            }, headers=headers)
            r.raise_for_status()
            d = r.json()
            items = d.get("proactive_context", [])
            if not items:
                return "No proactive context to surface."
            lines = ["Proactive context from the mind:"]
            for item in items[:5]:
                lines.append(f"  - [{item['type']}] {item['content']} (relevance {item['relevance']:.2f})")
            return "\n".join(lines)

        else:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {tool}")


@mcp_router.get("/sse")
async def mcp_sse(request: Request):
    async def stream():
        # Required first event: tell the client where to POST tool calls
        yield "event: endpoint\ndata: /mcp\n\n"
        while True:
            await asyncio.sleep(15)
            yield ": keepalive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@mcp_router.post("")
@mcp_router.post("/")
async def mcp_post(request: Request):
    body = await request.json()
    method = body.get("method", "")
    msg_id = body.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "serverInfo": {"name": "nexus", "version": "1.0.0"},
        }}

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    elif method == "tools/call":
        params = body.get("params", {})
        try:
            result = await _dispatch(params.get("name", ""), params.get("arguments", {}), request)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": result}]}}
        except Exception as e:
            log.error("Tool %s failed: %s", params.get("name"), e)
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(e)}}

    elif method.startswith("notifications/"):
        # Notifications must not be responded to per MCP spec
        from fastapi.responses import Response
        return Response(status_code=204)

    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown: {method}"}}
