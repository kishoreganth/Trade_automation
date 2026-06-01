# Automation_TRADE

NSE & BSE corporate announcement monitoring platform with quarterly result extraction, PE analysis, and a real-time Next.js dashboard.

**Stack:** FastAPI · Celery · PostgreSQL · Redis · Next.js 14

---

## Quick Start

Docker runs **only PostgreSQL + Redis**. Backend and frontend run directly in your terminal.

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop

### 1. Setup (one-time, run from project root)

```bash
copy .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
```

Edit `.env` with your API keys. Defaults work for local DB/Redis.

### 2. Start DB & Redis (Docker)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
```

### 3. Run Migrations (one-time, from project root)

```bash
.venv\Scripts\activate
cd backend
alembic upgrade head
```

> All terminals below assume you start from the **project root** directory.

### 4. Backend API (Terminal 1)

```bash
cd C:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE
.venv\Scripts\activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

### 5. Celery IO Worker (Terminal 2)

```bash
cd C:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE
.venv\Scripts\activate
cd backend
python -m celery -A worker.celery_app worker -Q io_queue -c 4 --pool=solo -n io@localhost --loglevel=info
```

### 6. Celery CPU Worker (Terminal 3)

```bash
cd C:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE
.venv\Scripts\activate
cd backend
python -m celery -A worker.celery_app worker -Q cpu_queue -c 2 --pool=solo -n cpu@localhost --loglevel=info
```

### 7. Celery Beat (Terminal 4)

```bash
cd C:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE
.venv\Scripts\activate
cd backend
python -m celery -A worker.celery_app beat --loglevel=info
```

### 8. Frontend (Terminal 5)

```bash
cd C:\Projects\STOCK-HIFI\Project_Market\Automation_TRADE\frontend
npm install
npm run dev
```

### Access

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:5000 |
| API Docs | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

---

## Stop Everything

```bash
# Ctrl+C in each terminal, then:
docker compose down

# Full reset (wipes DB data):
docker compose down -v
```

---

## Production (Full Docker)

```bash
docker compose up -d --build
```

Runs the entire stack (Nginx, Frontend, API, Workers, Beat, Postgres, Redis) at http://localhost:5000.

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
├── .venv/                       # Python venv (project root)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Pydantic settings
│   │   ├── database.py          # Async PostgreSQL
│   │   ├── cache.py             # Redis cache + PubSub
│   │   ├── routers/             # API endpoints
│   │   ├── services/
│   │   │   ├── nse_fetcher.py   # NSE announcements
│   │   │   ├── bse_fetcher.py   # BSE announcements
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
# New DB migration
cd backend && alembic revision --autogenerate -m "description"

# Trigger manual NSE fetch
curl -X POST http://localhost:8000/api/jobs/fetch_nse/start

# Run tests
cd backend && pytest
```
