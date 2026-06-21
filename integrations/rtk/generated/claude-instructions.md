# Claude RTK Instructions

Prefer RTK for noisy shell commands. If Nexus credentials are configured, use
`scripts/nexus-rtk <command>` so Nexus records compact command telemetry. If the
native Claude RTK hook is installed, commands may be rewritten automatically;
otherwise explicitly use `scripts/nexus-rtk <command>` or `rtk <command>`.

Verify with `rtk gain`. Continue using Nexus MCP for durable memory.
