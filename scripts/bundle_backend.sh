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
cd "$PROJECT_ROOT/shipagent-frontend"
npm ci --prefer-offline --no-audit
npx nx run-many -t build --all --configuration=production
./scripts/link-remotes.sh
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
# Uses --port 0 (OS-assigned) to avoid TOCTOU race on busy CI runners.
echo "--- Smoke test ---"
SMOKE_PORT=""
# Hermetic: throwaway data dir and no keychain access, so the smoke test never
# touches the operator's real database, labels, or credentials.
SMOKE_DATA_DIR="$(mktemp -d)"
PID=""
# Also stop the smoke sidecar on any abort (set -e) so it is never orphaned.
trap 'if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi; rm -rf "$SMOKE_DATA_DIR"' EXIT
# SMOKE_LAUNCH_BEGIN
(
cd "$SMOKE_DATA_DIR"
exec env -i PATH="$PATH" HOME="$SMOKE_DATA_DIR" \
PYTHON_DOTENV_DISABLED=1 \
SHIPAGENT_DATA_DIR="$SMOKE_DATA_DIR" \
SHIPAGENT_KEYRING_DISABLED=1 \
DATABASE_URL="sqlite:///$SMOKE_DATA_DIR/shipagent.db" \
FILTER_TOKEN_SECRET="smoke-test-filter-secret-000000000000" \
    "$BINARY" serve --port 0
) > "$BINARY_DIR/.smoke_stdout" 2>&1 &
PID=$!
# SMOKE_LAUNCH_END

# Wait up to 30 seconds for the SHIPAGENT_PORT= protocol line
for i in $(seq 1 60); do
    if [ -f "$BINARY_DIR/.smoke_stdout" ]; then
        # No match yet is expected while the sidecar starts; `|| true` keeps
        # `set -e -o pipefail` from aborting the wait loop (and orphaning $PID).
        SMOKE_PORT=$(grep -o 'SHIPAGENT_PORT=[0-9]*' "$BINARY_DIR/.smoke_stdout" | head -1 | cut -d= -f2 || true)
        if [ -n "$SMOKE_PORT" ]; then
            break
        fi
    fi
    sleep 0.5
done

if [ -z "$SMOKE_PORT" ]; then
    echo "Health check: FAILED (could not determine port)"
    cat "$BINARY_DIR/.smoke_stdout" 2>/dev/null || true
    kill $PID 2>/dev/null || true
    rm -f "$BINARY_DIR/.smoke_stdout"
    exit 1
fi

echo "Sidecar bound to port $SMOKE_PORT"

smoke_fail() {
    echo "$1: FAILED"
    kill $PID 2>/dev/null || true
    rm -f "$BINARY_DIR/.smoke_stdout"
    exit 1
}

BASE_URL="http://127.0.0.1:${SMOKE_PORT}"
curl -sf "$BASE_URL/health" > /dev/null 2>&1 || smoke_fail "Health check"
echo "Health check: PASSED"

# The data-source MCP child is this same binary, so a 200 here proves the
# frozen app can spawn and handshake with a bundled MCP server.
STATUS_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/v1/data-sources/status" || true)
[ "$STATUS_CODE" = "200" ] || smoke_fail "Data-source status (HTTP $STATUS_CODE)"
echo "Data-source status: PASSED"

# Deterministic synthetic workbook proves the bundled Excel adapter imports.
SMOKE_XLSX="$SMOKE_DATA_DIR/smoke.xlsx"
.venv/bin/python - "$SMOKE_XLSX" <<'PY'
import sys
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["name", "city"])
ws.append(["Alice Example", "Springfield"])
ws.append(["Bob Example", "Shelbyville"])
wb.save(sys.argv[1])
PY
IMPORT_BODY=$(curl -s -X POST "$BASE_URL/api/v1/data-sources/import" \
    -H 'Content-Type: application/json' \
    -d "{\"type\":\"excel\",\"file_path\":\"$SMOKE_XLSX\"}" || true)
echo "$IMPORT_BODY" | grep -Eq '"row_count": *2[^0-9]' || smoke_fail "Excel import ($IMPORT_BODY)"
echo "Excel import: PASSED"

kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true
PID=""
rm -f "$BINARY_DIR/.smoke_stdout"

echo "=== Build complete ==="
echo "Output: $BINARY_DIR/ (one-folder build)"
