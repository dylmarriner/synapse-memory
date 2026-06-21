#!/usr/bin/env bash
set -euo pipefail

echo "== Nexus + RTK setup =="

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

has_correct_rtk() {
  command -v rtk >/dev/null 2>&1 && rtk gain >/dev/null 2>&1
}

if has_correct_rtk; then
  echo "RTK already installed: $(command -v rtk)"
  rtk --version || true
else
  if command -v rtk >/dev/null 2>&1; then
    echo "A command named rtk exists, but 'rtk gain' failed. This may be the wrong RTK package."
    echo "If installed with cargo, run: cargo uninstall rtk"
    exit 1
  fi

  echo "Installing RTK from rtk-ai/rtk..."
  curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
fi

if ! has_correct_rtk; then
  echo "RTK install verification failed. Ensure ~/.local/bin or ~/.cargo/bin is on PATH." >&2
  exit 1
fi

echo "RTK token savings command works."
rtk gain || true

if [[ "${RTK_TELEMETRY_OPT_IN:-0}" != "1" ]]; then
  export RTK_TELEMETRY_DISABLED=1
  rtk telemetry disable >/dev/null 2>&1 || true
  echo "RTK telemetry disabled for this setup. Set RTK_TELEMETRY_OPT_IN=1 to opt in."
fi

if [[ "${RTK_INIT_CLAUDE:-0}" == "1" ]]; then
  echo "Initializing RTK Claude hooks..."
  rtk init -g --auto-patch
  rtk init --show || true
else
  echo "Skipping Claude hook patch. To enable: RTK_INIT_CLAUDE=1 bash scripts/setup-rtk.sh"
fi

echo "Done. Agents should use: rtk git status, rtk git diff, rtk pytest, rtk grep, rtk ls, etc."
echo "To generate per-agent snippets for Cline, Claude, Devin CLI, Hermes, OpenClaw, and OpenCode, run:"
echo "  bash scripts/connect-rtk-agents.sh"
echo "To scan and auto-connect all supported agents/IDEs, run:"
echo "  scripts/nexus-doctor          # dry-run"
echo "  scripts/nexus-doctor --apply  # writes configs with backups"
