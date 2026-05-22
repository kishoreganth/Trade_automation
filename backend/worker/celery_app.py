"""
Celery application configuration.
Broker: Redis DB 1 | Results: Redis DB 2

Run workers (Windows — use --pool=threads, fork is unsupported):
    # I/O worker (API calls, fetches, telegram)
    celery -A worker.celery_app worker -Q io_queue -n io@%COMPUTERNAME% --pool=threads --concurrency=8 --loglevel=info

    # CPU worker (OCR, AI extraction, PDF processing) — main parallelism for PE Pending
    celery -A worker.celery_app worker -Q cpu_queue -n cpu@%COMPUTERNAME% --pool=threads --concurrency=12 --loglevel=info

    # Beat scheduler (periodic tasks)
    celery -A worker.celery_app beat --loglevel=info

Linux/Docker — use --pool=prefork:
    celery -A worker.celery_app worker -Q cpu_queue -c 8 --pool=prefork
"""

import os
import sys
from pathlib import Path
from celery import Celery
from celery.schedules import crontab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery("automation_trade")

app.conf.update(
    broker_url=BROKER_URL,
    result_backend=RESULT_BACKEND,
    result_expires=3600,

    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="Asia/Kolkata",
    enable_utc=False,

    # Task routing: separate I/O-bound from CPU-bound
    task_routes={
        "worker.tasks.announcements.*": {"queue": "io_queue"},
        "worker.tasks.quotes.*": {"queue": "io_queue"},
        "worker.tasks.extraction.*": {"queue": "cpu_queue"},
        "worker.tasks.concall.*": {"queue": "cpu_queue"},
        "worker.tasks.announcement_insight.*": {"queue": "cpu_queue"},
    },

    # Default queue for unrouted tasks
    task_default_queue="io_queue",

    # Retry settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Rate limiting (max 5 concurrent OCR/AI tasks)
    worker_max_tasks_per_child=200,

    # Beat schedule — imported from beat_schedule.py
    beat_schedule={},
)

# Explicitly include all task modules
app.conf.include = [
    "worker.tasks.announcements",
    "worker.tasks.extraction",
    "worker.tasks.concall",
    "worker.tasks.announcement_insight",
    "worker.tasks.quotes",
]

# Import beat schedule
from .beat_schedule import BEAT_SCHEDULE  # noqa: E402
app.conf.beat_schedule = BEAT_SCHEDULE
