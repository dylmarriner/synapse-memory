# Nexus Agent Instructions

Nexus is available for durable memory.

- REST: `http://100.93.75.87:7777/v1`
- MCP: `http://100.93.75.87:7777/mcp`
- Agent ID: `project-agents`

Use Nexus memory tools for durable preferences, lessons, fixes, decisions, and handoffs.
Use `./scripts/nexus-rtk <command>` from the repo root for noisy shell commands when possible; fall back to `rtk <command>` if the wrapper is unavailable.
Do not store raw command noise as memory; save durable summaries and lessons only.

This repository runs in direct agent-to-memory mode by default. The optional Living Mind / LLM layer is disabled unless explicitly enabled.
