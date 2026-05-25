#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════
# Synapse Enterprise — Install Script
# Installs the MCP server as a systemd user service,
# and optionally installs the OpenClaw plugin.
# ══════════════════════════════════════════════════════════════════════

SYNAPSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${SYNAPSE_DIR}/.venv"
SERVICE_NAME="synapse-mcp"
SERVICE_SRC="${SYNAPSE_DIR}/systemd/synapse-mcp.service"
SERVICE_DST="${HOME}/.config/systemd/user/synapse-mcp.service"

echo "==> Synapse Enterprise Installer"
echo "    Source: ${SYNAPSE_DIR}"

# ── Step 1: Create virtual environment if missing ────────────────────
if [ ! -f "${VENV_DIR}/bin/python" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "${VENV_DIR}"
fi

# ── Step 2: Install dependencies ─────────────────────────────────────
echo "==> Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install --quiet mcp numpy ulid-py zstandard cryptography PyJWT

# ── Step 3: Install systemd service ─────────────────────────────────
echo "==> Installing systemd user service..."
mkdir -p "${HOME}/.config/systemd/user"
cp "${SERVICE_SRC}" "${SERVICE_DST}"
systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}"
systemctl --user restart "${SERVICE_NAME}"
echo "    Service: ${SERVICE_NAME} (port 8765)"

# ── Step 4: Install Python SDK ───────────────────────────────────────
echo "==> Installing Python SDK..."
"${VENV_DIR}/bin/pip" install --quiet -e "${SYNAPSE_DIR}/sdk/python"

# ── Step 5: OpenClaw plugin (optional) ──────────────────────────────
if [ -n "${OPENCLAW_ROOT:-}" ] || [ -d "../openclaw" ]; then
    OC_ROOT="${OPENCLAW_ROOT:-$(cd "${SYNAPSE_DIR}/.." && pwd)/openclaw}"
    if [ -f "${OC_ROOT}/package.json" ]; then
        echo "==> Installing OpenClaw plugin..."
        node "${SYNAPSE_DIR}/plugins/openclaw-synapse/scripts/install-to-openclaw.mjs"
    fi
fi

echo ""
echo "==> Installation complete!"
echo "    Server: http://localhost:8765/mcp"
echo "    Status: systemctl --user status ${SERVICE_NAME}"
echo "    Logs:   journalctl --user -u ${SERVICE_NAME} -f"
