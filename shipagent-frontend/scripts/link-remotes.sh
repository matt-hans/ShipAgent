#!/bin/sh
# Link remote build outputs into shell dist for unified serving.
# Run after: npx nx build shell --configuration=production
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST="$SCRIPT_DIR/../dist/apps/shell/browser"

if [ ! -d "$DIST" ]; then
  echo "ERROR: Shell dist not found at $DIST"
  echo "Run 'npx nx build shell --configuration=production' first."
  exit 1
fi

for remote in chat-remote sidebar-remote settings-remote domain-remote; do
  REMOTE_DIST="$SCRIPT_DIR/../dist/apps/$remote/browser"
  if [ ! -d "$REMOTE_DIST" ]; then
    echo "WARNING: $remote dist not found at $REMOTE_DIST — skipping"
    continue
  fi
  ln -sfn "../../$remote/browser" "$DIST/$remote"
  echo "Linked $remote"
done

echo "All remotes linked. Serve from: $DIST"
