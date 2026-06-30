#!/bin/bash
# nexus-code-watch.sh — auto-reindex a repo when its source files change
# Runs as a cron job (e.g. */5 min) or in a long-running loop.
#
# Usage:
#   ./nexus-code-watch.sh <repo_name> <path> [interval_seconds]
# Default interval: 300s (5 min)
#
# For real-time, use inotifywait (Linux) or fswatch (macOS). This script
# uses mtime polling so it works without extra dependencies.

set -uo pipefail

REPO_NAME="${1:-nexus-self}"
REPO_PATH="${2:-/app}"
INTERVAL="${3:-300}"

NEXUS_URL="${NEXUS_URL:-http://100.93.75.87:7777}"
NEXUS_SECRET="${NEXUS_SECRET:-nexus-memory-shared-key-2026}"

if [ ! -d "$REPO_PATH" ]; then
  echo "error: $REPO_PATH is not a directory"
  exit 1
fi

# Build a list of (file, mtime) and hash it.  When the hash changes,
# re-index.
prev_hash=""
while true; do
  cur_hash=$(find "$REPO_PATH" \
    -type f \
    \( -name "*.py" -o -name "*.js" -o -name "*.jsx" -o -name "*.ts" -o -name "*.tsx" \
       -o -name "*.go" -o -name "*.rs" -o -name "*.java" -o -name "*.kt" \
       -o -name "*.rb" -o -name "*.cpp" -o -name "*.hpp" -o -name "*.cs" \
       -o -name "*.swift" -o -name "*.scala" -o -name "*.lua" -o -name "*.php" \) \
    ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/__pycache__/*" \
    ! -path "*/venv/*" ! -path "*/.venv/*" ! -path "*/dist/*" ! -path "*/build/*" \
    -printf '%T@ %p\n' 2>/dev/null \
    | sort \
    | sha256sum | head -c 64)

  if [ "$cur_hash" != "$prev_hash" ] && [ -n "$cur_hash" ]; then
    if [ -n "$prev_hash" ]; then
      echo "$(date -Iseconds) changes detected — re-indexing $REPO_NAME at $REPO_PATH"
      response=$(curl -sf -X POST "$NEXUS_URL/v1/code/repos" \
        -H "Authorization: Bearer $NEXUS_SECRET" \
        -H "Content-Type: application/json" \
        --max-time 120 \
        -d "{\"name\":\"$REPO_NAME\",\"root_path\":\"$REPO_PATH\",\"max_files\":5000}" 2>&1)
      if [ $? -eq 0 ]; then
        files=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('files_indexed','?'))" 2>/dev/null || echo "?")
        syms=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('symbols','?'))" 2>/dev/null || echo "?")
        edges=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('edges','?'))" 2>/dev/null || echo "?")
        ms=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('duration_ms','?'))" 2>/dev/null || echo "?")
        echo "  re-indexed: $files files, $syms symbols, $edges edges in ${ms}ms"
      else
        echo "  re-index failed: $response"
      fi
    else
      echo "$(date -Iseconds) initial hash captured for $REPO_NAME"
    fi
    prev_hash="$cur_hash"
  fi
  sleep "$INTERVAL"
done
