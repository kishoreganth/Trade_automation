-- Postgres bootstrap: extensions only.
-- All table/index/seed creation is owned by Alembic (backend/alembic/versions/*).
-- This file runs ONCE on first Postgres container boot via docker-entrypoint-initdb.d.

CREATE EXTENSION IF NOT EXISTS "pg_trgm";
