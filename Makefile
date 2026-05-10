.PHONY: up down build logs migrate dev

# Start full production stack
up:
	docker compose up -d

# Stop all services
down:
	docker compose down

# Rebuild and restart
build:
	docker compose up -d --build

# View all logs
logs:
	docker compose logs -f

# View specific service logs
logs-%:
	docker compose logs -f $*

# Run SQLite -> PostgreSQL migration
migrate:
	python scripts/migrate_sqlite_to_postgres.py

# Run Alembic migrations
alembic-up:
	cd backend && alembic upgrade head

# Dev mode (just postgres + redis for local development)
dev:
	docker compose up -d postgres redis

# Verify setup
verify:
	python scripts/verify_setup.py

# Health check
health:
	curl -s http://localhost/health | python -m json.tool

# Scale workers
scale-io:
	docker compose up -d --scale celery-io=3

scale-cpu:
	docker compose up -d --scale celery-cpu=2
