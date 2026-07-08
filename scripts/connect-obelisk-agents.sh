#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATED_DIR="$ROOT_DIR/integrations/obelisk/generated"
mkdir -p "$GENERATED_DIR"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "== Obelisk agent connector =="

if ! command -v obelisk >/dev/null 2>&1; then
  echo "Obelisk not found. Install it first, then rerun this script."
  exit 1
fi

if ! obelisk doctor >/dev/null 2>&1; then
  echo "Obelisk is on PATH, but 'obelisk doctor' failed. Fix the install before continuing." >&2
  exit 1
fi

echo "Obelisk OK: $(command -v obelisk)"
obelisk --version || true

cat > "$GENERATED_DIR/shell-env.sh" <<'EOF'
# Source this before launching agents that execute shell commands.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
EOF

cat > "$GENERATED_DIR/claude-instructions.md" <<'EOF'
# Claude Obelisk Instructions

Prefer Obelisk for noisy shell commands. Use `obelisk run <command>` when
command output would otherwise flood context. Use `obelisk pack` for large
handoffs, `obelisk outline` before reading big files, and `obelisk symbol` when
a single function or class is enough.

Continue using Nexus MCP for durable memory.
EOF

cat > "$GENERATED_DIR/devin-cli-instructions.md" <<'EOF'
# Devin CLI Obelisk Instructions

Source `shell-env.sh` before launching Devin CLI so Obelisk is on PATH.

Tell Devin to use `obelisk run` for noisy shell commands (`git`, `ls`, `grep`,
tests, docker/kubectl). Use `obelisk pack`, `obelisk outline`, and
`obelisk symbol` when compact context is better than raw file reads.
EOF

cat > "$GENERATED_DIR/hermes-instructions.md" <<'EOF'
# Hermes Obelisk Instructions

Run Hermes with `obelisk` on PATH. Keep the Nexus plugin for durable memory.
Prefer `obelisk run` for noisy commands and `obelisk pack` for large context
bundles.
EOF

cat > "$GENERATED_DIR/openclaw-instructions.md" <<'EOF'
# OpenClaw Obelisk Instructions

Run OpenClaw with `obelisk` on PATH. Keep the Nexus Memory plugin for durable
memory. Prefer `obelisk run` for noisy shell commands and `obelisk pack` for
larger handoffs.
EOF

cat > "$GENERATED_DIR/opencode-instructions.md" <<'EOF'
# OpenCode Obelisk Instructions

Run OpenCode from a shell where `obelisk` is on PATH. Keep Nexus MCP configured.
Use `obelisk run` for noisy shell commands, `obelisk pack` for handoffs, and
`obelisk symbol` before reading large files.
EOF

echo "Generated snippets: $GENERATED_DIR"
find "$GENERATED_DIR" -maxdepth 1 -type f -print | sort
