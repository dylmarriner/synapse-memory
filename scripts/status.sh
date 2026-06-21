#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════"
echo "  Agent Memory Nexus — Status"
echo "═══════════════════════════════════════════"
echo ""

# Docker compose services
echo "Docker services:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  (not running)"

echo ""
echo "Backend health:"

# Nexus
echo -n "  Nexus (7777):       "
if curl -sf http://localhost:7777/health > /dev/null 2>&1; then
    echo "✅ healthy"
else
    echo "❌ unreachable"
fi

# agentmemory
echo -n "  agentmemory (3111): "
if curl -sf http://localhost:3111/agentmemory/health > /dev/null 2>&1; then
    echo "✅ healthy"
else
    echo "❌ unreachable"
fi

# hindsight
echo -n "  hindsight (8888):   "
if curl -sf http://localhost:8888/health > /dev/null 2>&1; then
    echo "✅ healthy"
else
    echo "❌ unreachable"
fi

echo ""
echo "Nexus full health:"
curl -sf http://localhost:7777/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (not available)"
