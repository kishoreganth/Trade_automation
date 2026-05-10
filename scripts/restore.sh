#!/bin/bash
# ─── PostgreSQL Restore Script ───
# Usage: ./scripts/restore.sh /path/to/backup.dump
#
# WARNING: This will DROP and recreate the database!

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup_file.dump>"
    echo ""
    echo "Available backups:"
    ls -la /opt/automation-trade/backups/daily/*.dump 2>/dev/null || echo "  No daily backups"
    ls -la /opt/automation-trade/backups/weekly/*.dump 2>/dev/null || echo "  No weekly backups"
    exit 1
fi

BACKUP_FILE="$1"
DB_NAME="${POSTGRES_DB:-automation_trade}"
DB_USER="${POSTGRES_USER:-trade_user}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "╔══════════════════════════════════════════╗"
echo "║  DATABASE RESTORE                        ║"
echo "╠══════════════════════════════════════════╣"
echo "║  File: $(basename "$BACKUP_FILE")"
echo "║  Database: $DB_NAME"
echo "║  Host: $DB_HOST:$DB_PORT"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "WARNING: This will DROP the current database!"
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo "[$(date)] Stopping application..."
docker compose stop api celery-io celery-cpu 2>/dev/null || true

echo "[$(date)] Dropping and recreating database..."
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS ${DB_NAME};"
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
    -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "[$(date)] Restoring from backup..."
PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --clean \
    --if-exists \
    --no-owner \
    "$BACKUP_FILE"

echo "[$(date)] Running Alembic stamp..."
cd /opt/automation-trade/backend
alembic stamp head

echo "[$(date)] Restarting application..."
docker compose start api celery-io celery-cpu

echo "[$(date)] Restore complete!"

# Verify
ROW_COUNT=$(PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -t -c "SELECT COUNT(*) FROM messages;")
echo "[$(date)] Verification: ${ROW_COUNT} messages in database"
