#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXUS_DIR="$(dirname "$SCRIPT_DIR")"

cd "$NEXUS_DIR"

echo "═══════════════════════════════════════════"
echo "  Agent Memory Nexus — Starting"
echo "═══════════════════════════════════════════"

# Check .env exists
if [ ! -f .env ]; then
    echo "⚠  No .env found — copying from .env.example"
    cp .env.example .env
    echo "   Edit .env and set NEXUS_SECRET and API keys, then re-run."
    exit 1
fi

echo "→ Starting all services..."
docker compose up -d

echo ""
echo "✓ Nexus is starting. Check status with: ./scripts/status.sh"
echo "✓ MCP endpoint:   http://$(hostname -I | awk '{print $1}'):7777/mcp"
echo "✓ REST endpoint:  http://$(hostname -I | awk '{print $1}'):7777/v1"
echo "✓ Dashboard:      http://$(hostname -I | awk '{print $1}'):7777/"
