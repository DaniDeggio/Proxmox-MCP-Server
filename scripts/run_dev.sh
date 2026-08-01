#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# run_dev.sh — start the MCP server for local development
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    echo "Loading .env file..."
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Default config path
export PROXMOX_MCP_CONFIG="${PROXMOX_MCP_CONFIG:-$SCRIPT_DIR/config/config.yaml}"
export PROXMOX_MCP_LOG_LEVEL="${PROXMOX_MCP_LOG_LEVEL:-DEBUG}"

echo "Config: $PROXMOX_MCP_CONFIG"
echo "Log level: $PROXMOX_MCP_LOG_LEVEL"

# Run the MCP server
if command -v uv &>/dev/null; then
    echo "Running with uv..."
    uv run proxmox-mcp-server "$@"
else
    echo "Running with Python..."
    python -m proxmox_mcp_server.server "$@"
fi

