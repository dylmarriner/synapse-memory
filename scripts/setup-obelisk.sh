#!/usr/bin/env bash
set -euo pipefail

echo "== Nexus + Obelisk setup =="

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

has_obelisk() {
  command -v obelisk >/dev/null 2>&1 && obelisk doctor >/dev/null 2>&1
}

if has_obelisk; then
  echo "Obelisk already installed: $(command -v obelisk)"
  obelisk --version || true
else
  if command -v obelisk >/dev/null 2>&1; then
    echo "A command named obelisk exists, but 'obelisk doctor' failed. This may be the wrong Obelisk package."
    exit 1
  fi

  cat <<'EOF'
Obelisk is not installed.

Install it from the Obelisk repository, then rerun this script:

  git clone https://github.com/dylmarriner/obelisk.git
  cd obelisk
  cargo build --release
  install -m755 target/release/obelisk ~/.local/bin/obelisk
EOF
  exit 1
fi

echo "Obelisk token savings command works."
obelisk stats || true

if [[ "${OBELISK_INIT_CLAUDE:-0}" == "1" ]]; then
  echo "Initializing Obelisk Claude hooks..."
  obelisk install claude
else
  echo "Skipping Claude hook install. To enable: OBELISK_INIT_CLAUDE=1 rerun this setup script."
fi

echo "Done. Agents should use: obelisk run git status, obelisk run git diff, obelisk run pytest, obelisk run rg, obelisk run ls, etc."
echo "To generate per-agent snippets for Claude, Codex, Hermes, OpenClaw, OpenCode, and Cline, run:"
echo "  bash scripts/connect-obelisk-agents.sh"
