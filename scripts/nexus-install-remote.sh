#!/usr/bin/env bash
# nexus-install-remote.sh — one-liner install for Nexus Memory
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dylanmarriner/shared-memory-mcp/main/scripts/nexus-install-remote.sh | bash
#   curl -fsSL ... | NEXUS_URL=http://x:7777 NEXUS_SECRET=abc bash
#   curl -fsSL ... | bash -s -- --all
#   curl -fsSL ... | bash -s -- paperclip opencode openclaw
#
# This script downloads the latest nexus-install Python script and runs it.
set -euo pipefail

REPO="${NEXUS_INSTALL_REPO:-dylanmarriner/shared-memory-mcp}"
BRANCH="${NEXUS_INSTALL_BRANCH:-main}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}/scripts/nexus-install"

echo "== Nexus Memory remote installer =="
echo "Source: ${RAW}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$RAW" -o "$TMP/nexus-install"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP/nexus-install" "$RAW"
else
  echo "ERROR: neither curl nor wget is available" >&2
  exit 1
fi

chmod +x "$TMP/nexus-install"
python3 "$TMP/nexus-install" "$@"
