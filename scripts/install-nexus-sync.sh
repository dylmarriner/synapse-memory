#!/bin/bash
# install-nexus-sync.sh — install nexus-sync cron on a single machine
# Usage: install-nexus-sync.sh <hostname>  (run from kubuntux)
set -e

if [ $# -lt 1 ]; then
  echo "usage: install-nexus-sync.sh <hostname> [agent_id]"
  exit 2
fi

HOST="$1"
AGENT_ID="${2:-$1}"
NEXUS_SECRET_VALUE="${NEXUS_SECRET:-nexus-memory-shared-key-2026}"
SCRIPT_PATH="\$HOME/.local/bin/nexus-sync.sh"

# Resolve the local repo root (the directory containing this installer script).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYNC_SCRIPT_SOURCE="$SCRIPT_DIR/nexus-sync.sh"

if [ ! -f "$SYNC_SCRIPT_SOURCE" ]; then
  echo "error: $SYNC_SCRIPT_SOURCE not found"
  exit 1
fi

echo "→ ${HOST}: copying nexus-sync.sh from $SYNC_SCRIPT_SOURCE"
ssh "$HOST" 'mkdir -p "$HOME/.local/bin" "$HOME/.config/nexus-sync"'
scp "$SYNC_SCRIPT_SOURCE" "${HOST}:./nexus-sync.sh"
ssh "$HOST" 'mv ~/nexus-sync.sh "$HOME/.local/bin/nexus-sync.sh" && chmod +x "$HOME/.local/bin/nexus-sync.sh"'

echo "→ ${HOST}: writing .env (NEXUS_SECRET, NEXUS_AGENT_ID, NEXUS_URL)"
ssh "$HOST" bash -s "$AGENT_ID" "$NEXUS_SECRET_VALUE" <<'REMOTE'
  set -e
  ENVFILE="$HOME/.config/nexus-sync/env"
  mkdir -p "$(dirname "$ENVFILE")"
  AGENT="$1"; SECRET="$2"
  cat > "$ENVFILE" <<EOF
export NEXUS_URL=http://100.93.75.87:7777
export NEXUS_SECRET=$SECRET
export NEXUS_AGENT_ID=$AGENT
EOF
  chmod 600 "$ENVFILE"
REMOTE

echo "→ ${HOST}: installing cron job (every 5 min)"
ssh "$HOST" bash -s <<'REMOTE'
  set -e
  CRONLINE="NEXUS_URL=http://100.93.75.87:7777 NEXUS_SECRET=nexus-memory-shared-key-2026 NEXUS_AGENT_ID=$(hostname -s) $HOME/.local/bin/nexus-sync.sh >> $HOME/.config/nexus-sync/cron.log 2>&1"
  TMP=$(mktemp)
  crontab -l 2>/dev/null | grep -v 'nexus-sync\.sh' > "$TMP" || true
  echo "*/5 * * * * $CRONLINE" >> "$TMP"
  crontab "$TMP"
  rm -f "$TMP"
  echo "  installed: $(crontab -l | grep nexus-sync)"
REMOTE

echo "→ ${HOST}: running sync once to verify"
ssh "$HOST" "NEXUS_URL=http://100.93.75.87:7777 NEXUS_SECRET=nexus-memory-shared-key-2026 NEXUS_AGENT_ID=${AGENT_ID} $SCRIPT_PATH" 2>&1 | head -10

echo "✓ ${HOST} ready"
