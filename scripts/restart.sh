#!/bin/bash
# Restart ShipAgent stack - kills existing processes and starts fresh

cd /Users/matthewhans/Desktop/Programming/ShipAgent

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
