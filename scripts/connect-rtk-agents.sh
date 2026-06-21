#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATED_DIR="$ROOT_DIR/integrations/rtk/generated"
mkdir -p "$GENERATED_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "== RTK agent connector =="

if ! command -v rtk >/dev/null 2>&1; then
  echo "RTK not found. Installing via scripts/setup-rtk.sh..."
  bash "$ROOT_DIR/scripts/setup-rtk.sh"
fi

if ! rtk gain >/dev/null 2>&1; then
  echo "A command named rtk exists, but 'rtk gain' failed. Wrong RTK package may be installed." >&2
  exit 1
fi

echo "RTK OK: $(command -v rtk)"
rtk --version || true

cat > "$GENERATED_DIR/shell-env.sh" <<'EOF'
# Source this before launching agents that execute shell commands.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export RTK_TELEMETRY_DISABLED=1
# Optional Nexus RTK event capture. Fill these in to let scripts/nexus-rtk post telemetry.
# export NEXUS_URL="http://localhost:7777"
# export NEXUS_SECRET="<secret>"
# export NEXUS_AGENT_ID="<agent-name>"
EOF

cat > "$GENERATED_DIR/cline-instructions.md" <<'EOF'
# Cline RTK Instructions

If Nexus credentials are configured, use the Nexus RTK wrapper for noisy shell
commands so command telemetry can be shown in the dashboard:

`scripts/nexus-rtk git status`, `scripts/nexus-rtk git diff`, `scripts/nexus-rtk grep`,
`scripts/nexus-rtk ls`, `scripts/nexus-rtk pytest`, `scripts/nexus-rtk npm test`.

If the wrapper is unavailable, fall back to `rtk <command>`.

Use raw commands or `rtk proxy <command>` only when exact unfiltered output is
required. Continue using Nexus MCP for durable memory.
EOF

cat > "$GENERATED_DIR/claude-instructions.md" <<'EOF'
# Claude RTK Instructions

Prefer RTK for noisy shell commands. If Nexus credentials are configured, use
`scripts/nexus-rtk <command>` so Nexus records compact command telemetry. If the
native Claude RTK hook is installed, commands may be rewritten automatically;
otherwise explicitly use `scripts/nexus-rtk <command>` or `rtk <command>`.

Verify with `rtk gain`. Continue using Nexus MCP for durable memory.
EOF

cat > "$GENERATED_DIR/devin-cli-instructions.md" <<'EOF'
# Devin CLI RTK Instructions

Before launching Devin CLI, source `shell-env.sh` so `rtk` is on PATH and Nexus
credentials are available if you want telemetry capture.

Tell Devin: use `scripts/nexus-rtk` for noisy shell commands (`git`, `ls`, `grep`,
tests, docker/kubectl). Fall back to `rtk` if the wrapper is unavailable. Use
`rtk proxy` or raw commands only when exact output is needed.
EOF

cat > "$GENERATED_DIR/hermes-instructions.md" <<'EOF'
# Hermes RTK Instructions

Run Hermes with `rtk` on PATH. Use Nexus plugin for memory. Prefix noisy shell
commands with `scripts/nexus-rtk` when available, otherwise `rtk`; use `rtk proxy`
when full unfiltered output is required.
EOF

cat > "$GENERATED_DIR/openclaw-instructions.md" <<'EOF'
# OpenClaw RTK Instructions

Run OpenClaw with `rtk` on PATH. Keep the Nexus Memory plugin for durable memory.
Use `scripts/nexus-rtk` for noisy shell commands when available, otherwise `rtk`.
Use `rtk proxy` when exact output is required.
EOF

cat > "$GENERATED_DIR/opencode-instructions.md" <<'EOF'
# OpenCode RTK Instructions

Run OpenCode from a shell where `rtk` is on PATH. Keep Nexus MCP configured.
Use `scripts/nexus-rtk` for noisy shell commands when available, otherwise `rtk`;
use raw commands/`rtk proxy` when exact output is required.
EOF

if [[ "${RTK_INIT_CLAUDE:-0}" == "1" ]]; then
  echo "Installing Claude RTK hook..."
  rtk init -g --auto-patch
  rtk init --show || true
else
  echo "Skipping Claude hook patch. To enable: RTK_INIT_CLAUDE=1 bash scripts/connect-rtk-agents.sh"
fi

echo "Generated snippets: $GENERATED_DIR"
find "$GENERATED_DIR" -maxdepth 1 -type f -print | sort
