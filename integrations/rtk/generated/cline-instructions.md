# Cline RTK Instructions

If Nexus credentials are configured, use the Nexus RTK wrapper for noisy shell
commands so command telemetry can be shown in the dashboard:

`scripts/nexus-rtk git status`, `scripts/nexus-rtk git diff`, `scripts/nexus-rtk grep`,
`scripts/nexus-rtk ls`, `scripts/nexus-rtk pytest`, `scripts/nexus-rtk npm test`.

If the wrapper is unavailable, fall back to `rtk <command>`.

Use raw commands or `rtk proxy <command>` only when exact unfiltered output is
required. Continue using Nexus MCP for durable memory.
