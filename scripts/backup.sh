#!/bin/bash
# ─── PostgreSQL Backup Script ───
# Schedule via cron: 0 2 * * * /opt/automation-trade/scripts/backup.sh
#
# Retention: keeps last 7 daily + 4 weekly backups

set -euo pipefail

# Config
BACKUP_DIR="/opt/automation-trade/backups"
DB_NAME="${POSTGRES_DB:-automation_trade}"
DB_USER="${POSTGRES_USER:-trade_user}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
RETENTION_DAILY=7
RETENTION_WEEKLY=4
DATE=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)

mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly"

echo "[$(date)] Starting backup..."

# ─── PostgreSQL dump ───
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --format=custom \
    --compress=9 \
    --file="${BACKUP_DIR}/daily/${DB_NAME}_${DATE}.dump"

BACKUP_SIZE=$(du -h "${BACKUP_DIR}/daily/${DB_NAME}_${DATE}.dump" | cut -f1)
echo "[$(date)] PostgreSQL backup: ${BACKUP_SIZE}"

# ─── Redis RDB snapshot ───
docker exec automation-trade-redis redis-cli BGSAVE 2>/dev/null || true
sleep 2
if [ -f "/var/lib/redis/dump.rdb" ]; then
    cp /var/lib/redis/dump.rdb "${BACKUP_DIR}/daily/redis_${DATE}.rdb"
    echo "[$(date)] Redis backup: done"
fi

# ─── Weekly backup (Sunday) ───
if [ "$DAY_OF_WEEK" -eq 7 ]; then
    cp "${BACKUP_DIR}/daily/${DB_NAME}_${DATE}.dump" \
       "${BACKUP_DIR}/weekly/${DB_NAME}_week_${DATE}.dump"
    echo "[$(date)] Weekly backup created"
fi

# ─── Cleanup old backups ───
find "${BACKUP_DIR}/daily" -name "*.dump" -mtime +${RETENTION_DAILY} -delete
find "${BACKUP_DIR}/daily" -name "*.rdb" -mtime +${RETENTION_DAILY} -delete
find "${BACKUP_DIR}/weekly" -name "*.dump" -mtime +$((RETENTION_WEEKLY * 7)) -delete

# ─── Verify backup integrity ───
pg_restore --list "${BACKUP_DIR}/daily/${DB_NAME}_${DATE}.dump" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "[$(date)] Backup verified: OK"
else
    echo "[$(date)] WARNING: Backup verification failed!"
    exit 1
fi

echo "[$(date)] Backup complete."
