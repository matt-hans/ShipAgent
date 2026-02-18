#!/usr/bin/env bash

set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_DIR:-/app/data/backups}"
retention_days="${AGENT_AUDIT_RETENTION_DAYS:-30}"
retention_days="${BACKUP_RETENTION_DAYS:-$retention_days}"

database_url="${DATABASE_URL:-}"
if [[ -n "$database_url" && "$database_url" == sqlite:* ]]; then
  db_path="${database_url#sqlite:///}"
elif [[ -n "${SHIPAGENT_DB_PATH:-}" ]]; then
  db_path="${SHIPAGENT_DB_PATH}"
else
  db_path="/app/data/shipagent.db"
fi

mkdir -p "$backup_dir"

if [[ ! -f "$db_path" ]]; then
  echo "Database file not found: $db_path"
  exit 1
fi

db_backup="${backup_dir}/shipagent_${timestamp}.db"
labels_backup="${backup_dir}/labels_${timestamp}.tar.gz"

sqlite3 "$db_path" ".backup '${db_backup}'"

if [[ -d "/app/labels" ]]; then
  tar -czf "$labels_backup" -C /app labels
fi

find "$backup_dir" -name "shipagent_*.db" -mtime "+${retention_days}" -delete
find "$backup_dir" -name "labels_*.tar.gz" -mtime "+${retention_days}" -delete

echo "Backup complete"
echo "  DB: $db_backup"
if [[ -f "$labels_backup" ]]; then
  echo "  Labels: $labels_backup"
fi
