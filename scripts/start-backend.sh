#!/bin/bash
# Start ShipAgent backend with all environment variables loaded
#
# Usage: ./scripts/start-backend.sh
#
# This script:
# 1. Loads all variables from .env
# 2. Starts uvicorn with hot-reload on port 8000

set -e

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and fill in your credentials."
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

# Backward compatibility: allow legacy ANTHROPIC_MODEL key.
if [ -z "${AGENT_MODEL:-}" ] && [ -n "${ANTHROPIC_MODEL:-}" ]; then
    export AGENT_MODEL="$ANTHROPIC_MODEL"
fi

if [ ! -x .venv/bin/python ]; then
    echo "Error: .venv is missing or incomplete."
    echo "Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
    exit 1
fi

if ! .venv/bin/python -c "import uvicorn, claude_agent_sdk" >/dev/null 2>&1; then
    echo "Error: backend dependencies are missing in .venv (uvicorn/claude_agent_sdk)."
    echo "Run: .venv/bin/python -m pip install -e '.[dev]'"
    exit 1
fi

echo "Starting ShipAgent backend..."
echo "  Model: ${AGENT_MODEL:-claude-haiku-4-5-20251001}"
echo "  Shopify: ${SHOPIFY_STORE_DOMAIN:-not configured}"
echo ""

# Always use project .venv Python so backend and MCP subprocesses share deps.
# ShipAgent currently supports single-worker operation only.
exec .venv/bin/python -m uvicorn src.api.main:app --reload --reload-dir src --workers 1 --port 8000
