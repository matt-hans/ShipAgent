#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: /app/scripts/restore.sh <db-backup-path> [labels-backup-path]"
  exit 1
fi

db_backup="$1"
labels_backup="${2:-}"

database_url="${DATABASE_URL:-}"
if [[ -n "$database_url" && "$database_url" == sqlite:* ]]; then
  db_path="${database_url#sqlite:///}"
elif [[ -n "${SHIPAGENT_DB_PATH:-}" ]]; then
  db_path="${SHIPAGENT_DB_PATH}"
else
  db_path="/app/data/shipagent.db"
fi

if [[ ! -f "$db_backup" ]]; then
  echo "DB backup not found: $db_backup"
  exit 1
fi

mkdir -p "$(dirname "$db_path")"
cp "$db_backup" "$db_path"

if [[ -n "$labels_backup" ]]; then
  if [[ ! -f "$labels_backup" ]]; then
    echo "Labels backup not found: $labels_backup"
    exit 1
  fi
  rm -rf /app/labels
  mkdir -p /app/labels
  tar -xzf "$labels_backup" -C /app
fi

echo "Restore complete"
echo "  DB restored to: $db_path"
if [[ -n "$labels_backup" ]]; then
  echo "  Labels restored from: $labels_backup"
fi

