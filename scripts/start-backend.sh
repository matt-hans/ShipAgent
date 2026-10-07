#!/bin/bash
# Start ShipAgent backend with all environment variables loaded
#
# Usage: ./scripts/start-backend.sh
#
# This script:
# 1. Loads all variables from SHIPAGENT_ENV_FILE (default .env)
# 2. Starts uvicorn with hot-reload on SHIPAGENT_PORT (default 8080)

set -e

cd "$(dirname "$0")/.."

SHIPAGENT_ENV_FILE="${SHIPAGENT_ENV_FILE:-.env}"
BACKEND_PYTHON="${SHIPAGENT_PYTHON:-.venv/bin/python}"

if [ ! -f "$SHIPAGENT_ENV_FILE" ]; then
    echo "Error: $SHIPAGENT_ENV_FILE not found. Copy .env.example to .env and fill in your credentials."
    exit 1
fi

# Load environment variables
set -a
source "$SHIPAGENT_ENV_FILE"
set +a

# Backward compatibility: allow legacy ANTHROPIC_MODEL key.
if [ -z "${AGENT_MODEL:-}" ] && [ -n "${ANTHROPIC_MODEL:-}" ]; then
    export AGENT_MODEL="$ANTHROPIC_MODEL"
fi

if [ ! -x "$BACKEND_PYTHON" ]; then
    echo "Error: backend Python is missing or incomplete at $BACKEND_PYTHON."
    echo "Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
    exit 1
fi

if ! "$BACKEND_PYTHON" - <<'PY' >/dev/null 2>&1
import httpx
import google.genai
import openai
import uvicorn
PY
then
    echo "Error: backend dependencies are missing in .venv."
    echo "Required runtime modules include uvicorn, httpx, openai, and google-genai."
    echo "Run: .venv/bin/python -m pip install -e '.[dev]'"
    exit 1
fi

SHIPAGENT_PORT="${SHIPAGENT_PORT:-8080}"
export SHIPAGENT_PORT

echo "Starting ShipAgent backend..."
echo "  Port: ${SHIPAGENT_PORT}"
echo "  Model: ${AGENT_MODEL:-claude-haiku-4-5-20251001}"
echo "  Shopify: ${SHOPIFY_STORE_DOMAIN:-not configured}"
echo ""

# Use the project .venv by default so backend and MCP subprocesses share deps.
# ShipAgent currently supports single-worker operation only.
exec "$BACKEND_PYTHON" -m uvicorn src.api.main:app --reload --reload-dir src --workers 1 --port "${SHIPAGENT_PORT}"
