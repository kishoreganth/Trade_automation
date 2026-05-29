# Automation_TRADE

NSE & BSE corporate announcement monitoring platform with quarterly result extraction, PE analysis, and a real-time Next.js dashboard.

**Stack:** FastAPI · Celery · PostgreSQL · Redis · Next.js 14

---

## Local Development Setup

Docker is used **only for PostgreSQL and Redis**. Everything else runs directly in terminal.

### Prerequisites

- Python 3.11+
- Node.js 18+ & npm
- Docker Desktop (for Postgres + Redis)

---

### 1. Clone & Environment

```bash
cd c:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE

# Create .env from template
copy .env.example .env
```

Edit `.env` and fill in your keys (Telegram, OpenAI, etc.). The defaults work for local Postgres/Redis.

---

### 2. Start PostgreSQL & Redis (Docker)

The dev override file exposes ports `5432` and `6379` to your host machine:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
```

Verify they're running with ports exposed:

```bash
docker compose ps
docker exec trade_postgres pg_isready -U trade_user -d automation_trade
docker exec trade_redis redis-cli ping
```

> **Important:** Without `-f docker-compose.dev.yml`, ports stay internal to Docker and your local backend can't connect.

---

### 3. Python Virtual Environment

```bash
cd backend
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Windows (CMD)
.\venv\Scripts\activate.bat

# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

---

### 4. Run Database Migrations (Alembic)

```bash
# From backend/ directory, with venv activated
alembic upgrade head
```

This creates all tables, indexes, and seeds the schema.

---

### 5. Start the FastAPI Backend

```bash
# From backend/ directory
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: http://localhost:8000/health

API docs: http://localhost:8000/docs

---

### 6. Start Celery Workers

Open **three separate terminals**, activate the venv in each, and run from `backend/`:

**Terminal 2 — I/O Worker** (fetches NSE/BSE announcements):

```bash
cd backend
.\venv\Scripts\Activate.ps1
celery -A worker.celery_app worker -Q io_queue -c 4 -n io@localhost --pool=solo --loglevel=info
```

**Terminal 3 — CPU Worker** (PDF extraction, OpenAI):

```bash
cd backend
.\venv\Scripts\Activate.ps1
celery -A worker.celery_app worker -Q cpu_queue -c 2 -n cpu@localhost --pool=solo --loglevel=info
```

**Terminal 4 — Beat Scheduler** (triggers periodic fetches every 60s):

```bash
cd backend
.\venv\Scripts\Activate.ps1
celery -A worker.celery_app beat --loglevel=info
```

> **Windows note:** Use `--pool=solo` instead of `--pool=prefork` since prefork doesn't work on Windows. For higher concurrency on Windows, use `--pool=threads`.

---

### 7. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard: http://localhost:5000

---

## Quick Reference — All Commands

Open 5 terminals side by side:

| Terminal | Directory | Command |
|----------|-----------|---------|
| 1 — Docker | root | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis` |
| 2 — API | `backend/` | `uvicorn app.main:app --reload --port 8000` |
| 3 — IO Worker | `backend/` | `celery -A worker.celery_app worker -Q io_queue -c 4 --pool=solo -n io@localhost --loglevel=info` |
| 4 — CPU Worker | `backend/` | `celery -A worker.celery_app worker -Q cpu_queue -c 2 --pool=solo -n cpu@localhost --loglevel=info` |
| 5 — Beat | `backend/` | `celery -A worker.celery_app beat --loglevel=info` |
| 6 — Frontend | `frontend/` | `npm run dev` |

> Activate the Python venv (`.\venv\Scripts\Activate.ps1`) in terminals 2, 3, 4, and 5 before running.

---

## Stopping Everything

```bash
# Stop Celery workers & beat: Ctrl+C in each terminal

# Stop Docker services
docker compose down

# Stop and remove volumes (full reset)
docker compose down -v
```

---

## Full Production Deployment (Docker)

To run the entire stack in Docker (no local terminals needed):

```bash
docker compose up -d --build
```

This starts: Nginx, Frontend, API, Celery IO (x20), Celery CPU (x4), Beat, Postgres, Redis.

Access via: http://localhost:5000

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | Postgres host |
| `POSTGRES_PORT` | `5432` | Postgres port |
| `POSTGRES_DB` | `automation_trade` | Database name |
| `POSTGRES_USER` | `trade_user` | DB user |
| `POSTGRES_PASSWORD` | `trade_secure_pwd_2026` | DB password |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for cache/pubsub |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |
| `TELEGRAM_ENABLED` | `false` | Enable Telegram alerts |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID |
| `OPENAI_API_KEY` | — | OpenAI key for PDF extraction |

---

## Project Structure

```
Automation_TRADE/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Pydantic settings
│   │   ├── database.py          # Async PostgreSQL
│   │   ├── cache.py             # Redis cache + PubSub
│   │   ├── routers/             # API endpoints
│   │   ├── services/
│   │   │   ├── nse_fetcher.py   # NSE announcements (nse lib)
│   │   │   ├── bse_fetcher.py   # BSE announcements (bse lib + httpx)
│   │   │   └── ocr_extractor.py # PDF → EPS → PE (OpenAI)
│   │   └── middleware/          # Auth, rate-limit, metrics
│   ├── worker/
│   │   ├── celery_app.py        # Celery config
│   │   ├── beat_schedule.py     # Periodic task schedule
│   │   └── tasks/               # Celery task definitions
│   ├── alembic/                 # DB migrations
│   └── requirements.txt
├── frontend/                    # Next.js 14 dashboard
├── docker-compose.yml           # Full production stack
├── docker-compose.dev.yml       # Dev overrides (ports exposed)
├── nginx/                       # Reverse proxy config
├── scripts/                     # DB init, migration, utilities
└── .env.example                 # Environment template
```

---

## Useful Commands

```bash
# Run Alembic migration
cd backend && alembic upgrade head

# Create new migration
cd backend && alembic revision --autogenerate -m "description"

# Check API health
curl http://localhost:8000/health

# Trigger manual NSE fetch (API running)
curl -X POST http://localhost:8000/api/jobs/fetch_nse/start

# Run tests
cd backend && pytest

# Load test
cd backend && locust -f tests/locustfile.py
```
