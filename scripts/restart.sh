#!/bin/bash
# Restart ShipAgent stack - kills existing processes and starts fresh
# Usage: ./scripts/restart.sh [--test|--prod]

cd /Users/matthewhans/Desktop/Programming/ShipAgent

UPS_TEST_URL="https://wwwcie.ups.com"
UPS_PROD_URL="https://onlinetools.ups.com"

# Parse arguments
ENV_MODE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            ENV_MODE="test"
            shift
            ;;
        --prod)
            ENV_MODE="prod"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--test|--prod]"
            exit 1
            ;;
    esac
done

# Update UPS_BASE_URL if flag provided
if [ -n "$ENV_MODE" ]; then
    if [ "$ENV_MODE" = "test" ]; then
        TARGET_URL="$UPS_TEST_URL"
        echo "Switching to UPS Test environment..."
    else
        TARGET_URL="$UPS_PROD_URL"
        echo "Switching to UPS Production environment..."
    fi

    # Update .env file
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|^UPS_BASE_URL=.*|UPS_BASE_URL=$TARGET_URL|" .env
    else
        # Linux
        sed -i "s|^UPS_BASE_URL=.*|UPS_BASE_URL=$TARGET_URL|" .env
    fi
    echo "UPS_BASE_URL set to: $TARGET_URL"
fi

# Kill existing processes
echo "Killing existing processes..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null
sleep 2
echo "Ports cleared."

# Start backend
echo "Starting backend..."
set -a && source .env && set +a && .venv/bin/python -m uvicorn src.api.main:app --reload --port 8000 > backend.log 2>&1 &

# Start frontend
echo "Starting frontend..."
(cd frontend && npm run dev > frontend.log 2>&1 &)

# Wait for services
sleep 5

# Reconnect Shopify
curl -s http://localhost:8000/api/v1/platforms/shopify/env-status > /dev/null

echo ""
echo "Stack restarted."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
