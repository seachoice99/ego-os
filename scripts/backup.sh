#!/usr/bin/env bash
# Ego OS backup (v0.4.1).
#
# Backs up the two things that actually matter -- the SQLite database and
# generated/published artifacts -- everything else is reproducible from
# git. Uses sqlite3's own .backup command (never a raw `cp`, which can
# copy a database mid-write) and keeps the last $RETENTION_DAYS worth of
# daily backups.
#
# This script is NOT scheduled anywhere yet -- it's proposed here for the
# Owner to install as a systemd timer (see DEPLOYMENT.md) or cron entry
# on the production VPS. Running it does not touch the running app.
#
# Usage: scripts/backup.sh [backup_dir]
# Default backup_dir: /opt/ego-os-backups (production) or ./backups (local)

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$APP_DIR/ego_os/ego_os.db"
GENERATED_DIR="$APP_DIR/ego_os/generated"
BACKUP_DIR="${1:-${EGO_OS_BACKUP_DIR:-$APP_DIR/backups}}"
RETENTION_DAYS="${EGO_OS_BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/ego_os_$STAMP.db'"
    echo "Backed up database -> $BACKUP_DIR/ego_os_$STAMP.db"
else
    echo "No database found at $DB_PATH -- nothing to back up yet." >&2
fi

if [ -d "$GENERATED_DIR" ]; then
    tar -czf "$BACKUP_DIR/generated_$STAMP.tar.gz" -C "$APP_DIR/ego_os" generated
    echo "Backed up generated artifacts -> $BACKUP_DIR/generated_$STAMP.tar.gz"
fi

# Retention: delete backups older than RETENTION_DAYS, this run's own
# files excluded by construction (they're brand new).
find "$BACKUP_DIR" -maxdepth 1 -name "ego_os_*.db" -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name "generated_*.tar.gz" -mtime "+$RETENTION_DAYS" -delete
