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
export DEGGIO_INFRA_CONFIG="${DEGGIO_INFRA_CONFIG:-$SCRIPT_DIR/config/config.yaml}"
export DEGGIO_INFRA_LOG_LEVEL="${DEGGIO_INFRA_LOG_LEVEL:-DEBUG}"

echo "Config: $DEGGIO_INFRA_CONFIG"
echo "Log level: $DEGGIO_INFRA_LOG_LEVEL"

# Run the MCP server
if command -v uv &>/dev/null; then
    echo "Running with uv..."
    uv run deggio-infra-mcp
else
    echo "Running with Python..."
    python -m deggio_infra_mcp.server
fi
