# AI Agent / IDE Target Registry

This registry tracks AI coding agents, IDEs, editor extensions, desktop agents,
and agent frameworks that Nexus Doctor should eventually discover and connect.

Integration classes:

- **MCP HTTP** — add Nexus `/mcp` URL and bearer header.
- **MCP stdio** — add `scripts/adapters/nexus_mcp_stdio.py` command.
- **Instructions** — write project/global instructions pointing to Nexus + RTK.
- **Env bootstrap** — write `NEXUS_URL`, `NEXUS_SECRET`, `NEXUS_AGENT_ID`, RTK vars.
- **Plugin** — install/copy a Nexus plugin or manifest.
- **REST/OpenAPI** — register Nexus REST/OpenAPI/plugin manifest.
- **Unknown/manual** — known product, integration format needs confirmation.

## Already implemented in Nexus Doctor v1

| Target | Category | Integration | Current path/pattern |
|---|---|---|---|
| Claude Desktop | desktop agent | MCP stdio | `~/.config/Claude/claude_desktop_config.json` |
| Claude Code | CLI agent | instructions / RTK hook | `~/.claude/CLAUDE.md`, `rtk init -g` |
| Cline standalone | VS Code-like extension | MCP stdio | `~/.cline/data/settings/cline_mcp_settings.json` |
| Cline in Windsurf | IDE extension | MCP HTTP | `~/.config/Windsurf/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Cline in Antigravity | IDE extension | MCP HTTP | `~/.config/Antigravity/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Cline in Trae | IDE extension | MCP HTTP | `~/.config/Trae/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Kade/Kilo in Windsurf | IDE extension | MCP HTTP | `globalStorage/kade.kade/settings/mcp_settings.json`, `kilocode.kilo-code` |
| Kade in Antigravity/Trae | IDE extension | MCP HTTP | `globalStorage/kade.kade/settings/mcp_settings.json` |
| Windsurf global | IDE | MCP HTTP | `~/.codeium/windsurf/mcp_config.json` |
| Antigravity global | IDE | MCP HTTP | `~/.gemini/antigravity/mcp_config.json` |
| VS Code MCP | IDE | MCP HTTP | `~/.vscode/mcp.json` |
| Cursor MCP | IDE | MCP HTTP | `~/.cursor/mcp.json` |
| OpenCode | CLI/agent | MCP stdio config | `~/.config/opencode/opencode.json` |
| Paperclip AI | plugin/desktop | config/plugin | `~/.config/paperclip/nexus-memory.json` |
| Hermes | agent runtime | env bootstrap/plugin | `~/.hermes/nexus.env` |
| OpenClaw | agent runtime | env bootstrap/plugin | `~/.openclaw/nexus.env` |
| Devin CLI | CLI agent | instructions | `~/.devin/NEXUS.md` |

## High-priority targets to add next

| Target | Category | Likely integration | Notes / likely paths |
|---|---|---|---|
| Gemini CLI | CLI agent | MCP + `GEMINI.md` instructions | Supports MCP servers in `~/.gemini/settings.json`; persistent context via `GEMINI.md`. Add Nexus MCP and RTK wrapper guidance. |
| Qwen Code | CLI/IDE/Desktop agent | MCP + instructions + hooks | Feature parity with Claude Code; supports MCP, hooks, auto-memory, skills, VS Code/Zed/JetBrains/Desktop/daemon. Likely `~/.qwen/settings.json`, `.qwen/`, `AGENTS.md`. |
| Codex CLI | CLI agent | `AGENTS.md` / `.codex` instructions | OpenAI terminal coding agent. Repo uses `AGENTS.md` and `.codex/`; config needs deeper confirmation. |
| Goose | desktop/CLI/API agent | MCP extension | Supports 70+ MCP extensions, desktop, CLI, API. Likely `~/.config/goose` or `~/.goose`; add Nexus MCP extension. |
| Continue.dev | VS Code/JetBrains/CLI | config/instructions/custom tools | Open-source coding agent, final 2.0.0; uses `.continue/` and config. Add Nexus instructions and possible REST/MCP tool if supported. |
| Aider | CLI pair programmer | repo instructions/env/wrapper | Terminal agent; no obvious MCP from repo summary. Add `.aider.conf.yml` or repo conventions if confirmed, plus RTK wrapper guidance. |
| Roo Code | VS Code extension | MCP config | Cline fork/family; likely similar globalStorage config. Search extension IDs: `rooveterinaryinc.roo-cline`, `roo-code`. |
| Kilo Code standalone | VS Code extension | MCP config | Already partially via Windsurf. Add VS Code/Trae/Antigravity patterns for `kilocode.kilo-code`. |
| Continue in JetBrains | IDE plugin | config/instructions | JetBrains plugin config path needs confirmation. |
| Zed Assistant | IDE | context server / settings / instructions | Zed has `.zed/`, `.agents/`, `AGENTS.md`; investigate exact MCP/context-server settings. |
| JetBrains AI Assistant | IDE | unknown/manual | May support MCP indirectly or only plugin-specific settings. Needs confirmation. |
| GitHub Copilot Chat / Agent | IDE extension | instructions only | No general MCP config. Add workspace instructions (`.github/copilot-instructions.md`) and RTK/Nexus guidance. |
| Sourcegraph Cody | IDE extension | instructions/context | Cody repo URL changed; investigate extension config and custom context support. |
| Tabby | self-hosted assistant | IDE/server config | Strong self-hosted assistant. More completion/chat than agent tools; add instructions/context if possible. |
| OpenHands / Agent Canvas | autonomous SWE agent | REST/env/tool config | Has local REST agent server/canvas. Add Nexus env/bootstrap and custom tool docs. |
| SWE-agent | autonomous SWE benchmark agent | env/instructions | Add Nexus env and RTK wrapper to workspace/container. |
| AutoCodeRover | autonomous SWE agent | env/instructions | Add Nexus env and RTK wrapper. |
| smol-ai/developer | autonomous codegen | env/instructions | Add Nexus memory instructions. |
| MetaGPT | multi-agent framework | env/tool module | Add Nexus REST tool/provider. |
| CrewAI | agent framework | tool module | Add Nexus REST tool. |
| LangGraph/LangChain agents | agent framework | tool module | Add Nexus tool/retriever. |
| AutoGen | agent framework | tool module | Add Nexus memory/tool adapter. |
| Flowise | low-code agent builder | REST/OpenAPI tool | Import Nexus OpenAPI or HTTP tool. |
| Dify | low-code agent platform | REST/OpenAPI tool | Import Nexus OpenAPI/tool provider. |
| Langflow | low-code agent builder | REST component | Add Nexus component/OpenAPI. |
| n8n AI agents | workflow agents | HTTP node/OpenAPI | Add Nexus HTTP/OpenAPI template. |
| OpenWebUI | chat UI/agent tools | OpenAPI/tool server | Add Nexus OpenAPI tool or MCP bridge if supported. |
| LibreChat Agents | chat UI/agent tools | OpenAPI/MCP depending version | Add Nexus plugin/OpenAPI. |
| AnythingLLM Agents | desktop/server agent | OpenAPI/REST | Add Nexus REST connector if supported. |
| Jan / LM Studio assistants | desktop local LLM | instructions/manual | Usually no agent tools; add instruction templates if applicable. |
| AionUI / Gemini CLI Desktop / Qwen Code Desktop | desktop wrappers | inherit Gemini/Qwen config | Detect app configs and write underlying Gemini/Qwen MCP config. |
| PearAI | IDE | Cursor/VS Code-like | Likely VS Code-compatible config; detect `~/.config/PearAI` and extension globalStorage. |
| Amp | CLI/agent | settings/instructions | Detected `~/.config/amp/settings.json` on this machine; investigate format. |
| Augment Code | IDE extension | unknown/manual | Investigate MCP/custom context support. |
| Replit Agent | cloud IDE | manual/instructions | Cloud config; likely not local auto-connect. |
| GitHub Copilot Coding Agent | cloud agent | repo instructions | Add `.github/copilot-instructions.md`; cannot local-config auto-connect. |
| Cursor Background Agents | IDE/cloud | Cursor MCP/instructions | Covered by Cursor MCP + project instructions. |

## IDE/editor families to scan

Nexus Doctor should scan VS Code-compatible extension storage for multiple apps:

- VS Code: `~/.config/Code/User`, `~/.vscode`
- VS Code Insiders: `~/.config/Code - Insiders/User`
- VSCodium: `~/.config/VSCodium/User`
- Cursor: `~/.config/Cursor/User`, `~/.cursor`
- Windsurf: `~/.config/Windsurf/User`, `~/.codeium/windsurf`
- Antigravity: `~/.config/Antigravity/User`, `~/.gemini/antigravity`
- Trae: `~/.config/Trae/User`
- PearAI: `~/.config/PearAI/User`

Extension globalStorage IDs to search:

- `saoudrizwan.claude-dev` — Cline
- `rooveterinaryinc.roo-cline` / `roo-code` — Roo Code
- `kilocode.kilo-code` — Kilo Code
- `kade.kade` — Kade
- `continue.continue` — Continue
- `sourcegraph.cody-ai` — Cody
- `github.copilot-chat` — Copilot Chat
- `tabbyml.vscode-tabby` — Tabby

## Project instruction files to manage

These should receive Nexus + RTK guidance where appropriate:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md` / `.qwen/`
- `.github/copilot-instructions.md`
- `.cursor/rules/*` / `.cursorrules`
- `.windsurfrules`
- `.clinerules`
- `.aider.conf.yml` / `.aider*` once format confirmed
- `.continue/` config/instructions once format confirmed

## Doctor implementation backlog

1. ✓ Declarative target registry JSON: `integrations/doctor/targets.json`.
2. ✓ Recursive VS Code-compatible `globalStorage` discovery for known extension IDs.
3. ✓ Gemini CLI MCP writer for `~/.gemini/settings.json`.
4. ✓ Qwen Code MCP writer (`~/.qwen/settings.json`, Gemini-compatible format).
5. ✓ Goose env bootstrap writer (`~/.goose/nexus.env`).
6. ✓ Codex CLI + Aider instruction file writers.
7. ✓ Roo Code and Kilo Code globalStorage writers across IDE families.
8. ✓ `GEMINI.md` and `QWEN.md` project instruction updaters.
9. ✓ Low-code OpenAPI templates in `integrations/low-code/` (Dify, Flowise,
      Langflow, n8n, OpenWebUI, LibreChat, AnythingLLM).
10. ✗ OpenHands/SWE-agent container env templates.
11. ✗ Continue.dev config writer (`.continue/` format — needs confirmation).
12. ✗ Zed context server writer (`~/.config/zed/settings.json`).
13. ✗ GitHub Copilot instructions writer (`.github/copilot-instructions.md`).
14. ✗ JetBrains AI Assistant integration (format needs investigation).
15. ✗ Amp config writer (`~/.config/amp/settings.json` — detected on dev machine,
       format not yet confirmed).
16. ✗ PearAI config writer (VS Code-compatible; check `~/.config/PearAI/User`).
