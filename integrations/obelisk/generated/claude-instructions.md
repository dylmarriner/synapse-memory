# Claude Obelisk Instructions

Prefer Obelisk for noisy shell commands. If Nexus credentials are configured, use
`scripts/nexus-obelisk <command>` so Nexus records compact command telemetry. If the
native Claude Obelisk hook is installed, commands may be rewritten automatically;
otherwise explicitly use `scripts/nexus-obelisk <command>` or `obelisk <command>`.

Verify with `obelisk doctor` and `obelisk stats`. Continue using Nexus MCP for durable memory.
