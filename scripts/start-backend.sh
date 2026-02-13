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

if [ ! -x .venv/bin/python3 ] || [ ! -x .venv/bin/uvicorn ]; then
    echo "Error: .venv is missing or incomplete."
    echo "Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
    exit 1
fi

echo "Starting ShipAgent backend..."
echo "  Model: ${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
echo "  Shopify: ${SHOPIFY_STORE_DOMAIN:-not configured}"
echo ""

# Always use project .venv so MCP subprocesses and backend share deps.
exec .venv/bin/uvicorn src.api.main:app --reload --reload-dir src --port 8000
