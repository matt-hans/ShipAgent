#!/usr/bin/env bash
# scripts/bump-version.sh
# Update version across all project manifests.
#
# Usage: ./scripts/bump-version.sh 1.2.3

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 1.2.3"
    exit 1
fi

VERSION="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Bumping version to $VERSION"

# 1. pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$PROJECT_ROOT/pyproject.toml"
echo "  Updated pyproject.toml"

# 2. tauri.conf.json
if [ -f "$PROJECT_ROOT/src-tauri/tauri.conf.json" ]; then
    # Use python for reliable JSON editing
    python3 -c "
import json, sys
with open('$PROJECT_ROOT/src-tauri/tauri.conf.json', 'r') as f:
    conf = json.load(f)
conf['version'] = '$VERSION'
with open('$PROJECT_ROOT/src-tauri/tauri.conf.json', 'w') as f:
    json.dump(conf, f, indent=2)
    f.write('\n')
"
    echo "  Updated tauri.conf.json"
fi

# 3. frontend/package.json
if [ -f "$PROJECT_ROOT/frontend/package.json" ]; then
    python3 -c "
import json
with open('$PROJECT_ROOT/frontend/package.json', 'r') as f:
    pkg = json.load(f)
pkg['version'] = '$VERSION'
with open('$PROJECT_ROOT/frontend/package.json', 'w') as f:
    json.dump(pkg, f, indent=2)
    f.write('\n')
"
    echo "  Updated frontend/package.json"
fi

# 4. Cargo.toml (if Tauri exists)
if [ -f "$PROJECT_ROOT/src-tauri/Cargo.toml" ]; then
    sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$PROJECT_ROOT/src-tauri/Cargo.toml"
    echo "  Updated Cargo.toml"
fi

echo "Version bumped to $VERSION across all manifests."
echo "Run: git add -u && git commit -m 'chore: bump version to v$VERSION'"
