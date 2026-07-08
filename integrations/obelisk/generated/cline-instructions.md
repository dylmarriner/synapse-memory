# Cline Obelisk Instructions

If Nexus credentials are configured, use the Nexus Obelisk wrapper for noisy shell
commands so command telemetry can be shown in the dashboard:

`scripts/nexus-obelisk git status`, `scripts/nexus-obelisk git diff`, `scripts/nexus-obelisk grep`,
`scripts/nexus-obelisk ls`, `scripts/nexus-obelisk pytest`, `scripts/nexus-obelisk npm test`.

If the wrapper is unavailable, fall back to `obelisk run <command>`.

Use raw commands only when exact unfiltered output is required. Continue using
Nexus MCP for durable memory.
