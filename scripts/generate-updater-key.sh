#!/usr/bin/env bash
# scripts/generate-updater-key.sh
# Generate the Ed25519 key pair for Tauri auto-updater.
#
# The PRIVATE key is a GitHub Secret (TAURI_SIGNING_PRIVATE_KEY).
# The PUBLIC key goes into tauri.conf.json.
#
# Usage: ./scripts/generate-updater-key.sh

set -euo pipefail

echo "=== Tauri Updater Key Generation ==="
echo ""
echo "This generates an Ed25519 key pair for signing auto-updates."
echo "You will be prompted for a password (stored as TAURI_SIGNING_PRIVATE_KEY_PASSWORD)."
echo ""

npx @tauri-apps/cli signer generate -w ~/.tauri/shipagent-updater.key

echo ""
echo "=== IMPORTANT ==="
echo "1. Add the PRIVATE key to GitHub Secrets as: TAURI_SIGNING_PRIVATE_KEY"
echo "2. Add the password to GitHub Secrets as: TAURI_SIGNING_PRIVATE_KEY_PASSWORD"
echo "3. Copy the PUBLIC key into src-tauri/tauri.conf.json under plugins.updater.pubkey"
echo "4. NEVER commit the private key to the repository."
