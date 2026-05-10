#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Automation_TRADE — universal container entrypoint.
#
#   1. Waits for Postgres to accept connections.
#   2. If RUN_MIGRATIONS=1:
#        a) runs `alembic upgrade head` (idempotent).
#        b) if /legacy/messages.db or /legacy/analytics.db exists AND the
#           `stocks` table is empty, runs the ONE-TIME SQLite -> Postgres
#           data import. After data is present this step auto-skips forever.
#        c) if MIGRATE_ONLY=1, exits 0 (used by the `migrate` sidecar).
#   3. Execs the container CMD (api / celery / etc).
#
# Subsequent deploys = `git pull && docker compose up -d --build`. Nothing else.
# ─────────────────────────────────────────────────────────────────────────────
set -e

PG_HOST="${POSTGRES_HOST:-postgres}"
PG_PORT="${POSTGRES_PORT:-5432}"
LEGACY_DIR="${LEGACY_SQLITE_DIR:-/legacy}"

echo "[entrypoint] Waiting for Postgres at ${PG_HOST}:${PG_PORT}..."
i=0
until python - <<'PY' 2>/dev/null
import asyncio, asyncpg, os, sys
async def main():
    c = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    await c.close()
asyncio.run(main())
PY
do
    i=$((i+1))
    if [ "$i" -ge 60 ]; then
        echo "[entrypoint] Postgres did not become ready after 120s — aborting."
        exit 1
    fi
    sleep 2
done
echo "[entrypoint] Postgres is up."

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] Applying Alembic migrations..."
    alembic upgrade head
    echo "[entrypoint] Alembic up to date."

    if [ -f "${LEGACY_DIR}/messages.db" ] || [ -f "${LEGACY_DIR}/analytics.db" ]; then
        ROW_COUNT=$(python - <<'PY'
import asyncio, asyncpg, os
async def main():
    c = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    n = await c.fetchval("SELECT COUNT(*) FROM stocks")
    await c.close()
    print(n)
asyncio.run(main())
PY
)
        if [ "$ROW_COUNT" = "0" ]; then
            echo "[entrypoint] Postgres is empty — running ONE-TIME SQLite -> Postgres import..."
            SQLITE_MESSAGES_DB="${LEGACY_DIR}/messages.db" \
            SQLITE_ANALYTICS_DB="${LEGACY_DIR}/analytics.db" \
            python /app/scripts/migrate_sqlite_to_postgres.py
            echo "[entrypoint] One-time SQLite import complete."
        else
            echo "[entrypoint] Postgres already has ${ROW_COUNT} stocks — skipping SQLite import."
        fi
    else
        echo "[entrypoint] No legacy SQLite files at ${LEGACY_DIR} — skipping SQLite import."
    fi

    if [ "${MIGRATE_ONLY:-0}" = "1" ]; then
        echo "[entrypoint] MIGRATE_ONLY=1 — exiting after migrations."
        exit 0
    fi
fi

echo "[entrypoint] Starting: $*"
exec "$@"
