#!/bin/sh
# Stage remote build outputs inside shell dist for unified serving.
# Run after: npx nx build shell --configuration=production
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_ROOT="${SHIPAGENT_FRONTEND_ROOT:-$SCRIPT_DIR/..}"
DIST="$FRONTEND_ROOT/dist/apps/shell/browser"
REMOTE_VALIDATOR="$SCRIPT_DIR/validate-remote-entry.mjs"

if [ ! -d "$DIST" ]; then
  echo "ERROR: Shell dist not found at $DIST"
  echo "Run 'npx nx build shell --configuration=production' first."
  exit 1
fi

for remote in chat-remote sidebar-remote settings-remote domain-remote; do
  REMOTE_DIST="$FRONTEND_ROOT/dist/apps/$remote/browser"
  if [ ! -d "$REMOTE_DIST" ]; then
    echo "ERROR: $remote dist not found at $REMOTE_DIST"
    exit 1
  fi
  REMOTE_ENTRY="$REMOTE_DIST/remoteEntry.json"
  if [ ! -f "$REMOTE_ENTRY" ] || [ -L "$REMOTE_ENTRY" ]; then
    echo "ERROR: $remote remoteEntry.json not found as a regular file"
    exit 1
  fi
  node "$REMOTE_VALIDATOR" "$REMOTE_DIST" "$remote"
  STAGED_REMOTE="$DIST/$remote"
  rm -rf "$STAGED_REMOTE"
  mkdir -p "$STAGED_REMOTE"
  cp -R "$REMOTE_DIST"/. "$STAGED_REMOTE"/
  node "$REMOTE_VALIDATOR" "$STAGED_REMOTE" "$remote"
  echo "Staged $remote"
done

echo "All remotes staged. Serve from: $DIST"
