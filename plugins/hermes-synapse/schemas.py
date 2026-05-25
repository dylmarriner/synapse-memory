"""Synapse Memory — Hermes plugin: tool schemas.

These schemas tell the LLM about the Synapse MCP tools available.
The actual execution happens via the MCP server (config.yaml mcp_servers.synapse),
not through direct Python handlers.
"""

SYNAPSE_HEALTH = {
    "name": "synapse_health",
    "description": "Check Synapse memory server status and get usage statistics (memories, devices, tenants, Tailscale IP).",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

SYNAPSE_STORE = {
    "name": "synapse_store",
    "description": (
        "Store a durable memory (convention, gotcha, architecture decision, "
        "fix, command, or note) into the persistent AI memory system. "
        "Memories survive across sessions and sync across all devices on the Tailscale mesh. "
        "Use this whenever you learn something the user or another agent will need later."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The memory content — be specific and include context",
            },
            "project_key": {
                "type": "string",
                "description": "Project scope (default: from config)",
                "default": "default",
            },
            "kind": {
                "type": "string",
                "enum": ["working", "episodic", "semantic"],
                "description": "Memory kind: working (ephemeral), episodic (timeline), semantic (knowledge)",
                "default": "semantic",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for discoverability",
            },
            "importance": {
                "type": "number",
                "description": "Importance 0.0-1.0. 0.9+ for critical, 0.7 for important, 0.5 for useful",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
            },
        },
        "required": ["content"],
    },
}

SYNAPSE_RETRIEVE = {
    "name": "synapse_retrieve",
    "description": (
        "Search the persistent AI memory system using hybrid keyword + semantic retrieval. "
        "Returns ranked memories with relevance scores. Call this before starting any task "
        "to see what's already known about the project."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — describe what you're looking for",
            },
            "project_key": {
                "type": "string",
                "description": "Scope to a project",
                "default": "default",
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": ["working", "episodic", "semantic"]},
                "description": "Filter by memory kinds",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (1-100)",
                "minimum": 1,
                "maximum": 100,
                "default": 10,
            },
        },
        "required": ["query"],
    },
}

SYNAPSE_UPDATE = {
    "name": "synapse_update",
    "description": "Update an existing memory. Use merge to append new info, overwrite to replace, or append to add to the end.",
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "Memory ID to update (get it from retrieve first)",
            },
            "content": {
                "type": "string",
                "description": "New content or content to append",
            },
            "merge_strategy": {
                "type": "string",
                "enum": ["merge", "overwrite", "append"],
                "description": "How to combine new content with existing",
                "default": "merge",
            },
        },
        "required": ["memory_id", "content"],
    },
}

SYNAPSE_DELETE = {
    "name": "synapse_delete",
    "description": "Delete a memory by ID. The deletion syncs across all devices.",
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "Memory ID to delete",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for audit trail",
            },
        },
        "required": ["memory_id"],
    },
}

SYNAPSE_CONTEXT = {
    "name": "synapse_context",
    "description": (
        "Get an optimized context pack for agent prompt injection. "
        "Returns pre-compressed, ranked memories matching the query. "
        "Use this at the START of any task to get relevant background context "
        "without consuming too many tokens."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you're about to work on — context pack is optimized for this",
            },
            "project_key": {
                "type": "string",
                "description": "Project scope",
                "default": "default",
            },
            "limit": {
                "type": "integer",
                "description": "Max context items to return",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
        },
    },
}

SYNAPSE_RANK = {
    "name": "synapse_rank",
    "description": "Rank memories by importance, access frequency, and decay. Shows which memories are most valuable and suggests retention/compression/archival actions.",
    "parameters": {
        "type": "object",
        "properties": {
            "project_key": {
                "type": "string",
                "description": "Project scope",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results",
                "minimum": 1,
                "maximum": 200,
                "default": 20,
            },
        },
    },
}

SYNAPSE_MEMORY = {
    "name": "synapse_memory",
    "description": "Get Synapse memory server diagnostics: database path, Tailscale IP, hostname, version, and counts of tenants/devices/memories/projects.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}
