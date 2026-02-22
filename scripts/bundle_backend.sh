#!/usr/bin/env bash
# scripts/bundle_backend.sh
# Build the ShipAgent Python sidecar using PyInstaller.
#
# Usage: ./scripts/bundle_backend.sh
# Output: dist/shipagent-core/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== ShipAgent Backend Bundler ==="
echo "Project root: $PROJECT_ROOT"

# 0. Validate updater pubkey is not placeholder
TAURI_CONF="$PROJECT_ROOT/src-tauri/tauri.conf.json"
if [ -f "$TAURI_CONF" ]; then
    if grep -q "REPLACE_WITH_ED25519_PUBLIC_KEY" "$TAURI_CONF"; then
        echo "ERROR: Updater pubkey is still placeholder in $TAURI_CONF"
        echo "  Run: ./scripts/generate-updater-key.sh"
        echo "  Then replace the pubkey value in tauri.conf.json"
        exit 1
    fi
fi

# 1. Build frontend first (bundled into the binary)
echo "--- Building frontend ---"
cd "$PROJECT_ROOT/frontend"
npm ci --prefer-offline --no-audit
npm run build
cd "$PROJECT_ROOT"

# 2. Run PyInstaller
echo "--- Running PyInstaller ---"
.venv/bin/python -m PyInstaller shipagent-core.spec --clean --noconfirm

# 3. Verify the one-folder output
echo "--- Verifying build ---"
BINARY_DIR="$PROJECT_ROOT/dist/shipagent-core"
BINARY="$BINARY_DIR/shipagent-core"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found at $BINARY"
    echo "Expected one-folder build at $BINARY_DIR/"
    exit 1
fi

SIZE=$(du -sh "$BINARY_DIR" | cut -f1)
echo "Bundle size: $SIZE"
echo "Binary path: $BINARY"

# 4. Smoke test — start server briefly and check /health
echo "--- Smoke test ---"
"$BINARY" serve --port 9876 &
PID=$!
sleep 5

if curl -sf http://127.0.0.1:9876/health > /dev/null 2>&1; then
    echo "Health check: PASSED"
else
    echo "Health check: FAILED"
    kill $PID 2>/dev/null || true
    exit 1
fi

kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

echo "=== Build complete ==="
echo "Output: $BINARY_DIR/ (one-folder build)"
