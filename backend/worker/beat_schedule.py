"""
Celery Beat schedule — replaces all asyncio.create_task() periodic loops.

Current in-process schedule:
  Job 1: NSE equities       — every 60s, offset 0s
  Job 2: BSE all            — every 60s, offset 20s
  Job 3: BSE results        — every 60s, offset 40s
  Job 4: BSE board meeting  — every 60s, offset 50s
  Scheduled fetch quotes    — daily at configured time (IST)

Celery Beat handles offsets via staggered start times.
"""

from celery.schedules import schedule, crontab

BEAT_SCHEDULE = {
    # ─── Announcement Fetchers (every 60s, staggered) ───
    "fetch-nse-equities": {
        "task": "worker.tasks.announcements.fetch_nse_equities",
        "schedule": 60.0,
        "options": {"queue": "io_queue", "countdown": 0},
    },
    "fetch-bse-all": {
        "task": "worker.tasks.announcements.fetch_bse_all_announcements",
        "schedule": 60.0,
        "options": {"queue": "io_queue", "countdown": 20},
    },
    "fetch-bse-results": {
        "task": "worker.tasks.announcements.fetch_bse_results",
        "schedule": 60.0,
        "options": {"queue": "io_queue", "countdown": 40},
    },
    "fetch-bse-board-meeting": {
        "task": "worker.tasks.announcements.fetch_bse_board_meeting",
        "schedule": 60.0,
        "options": {"queue": "io_queue", "countdown": 50},
    },

    # ─── Scheduled Fetch Quotes (weekdays 12:40 IST) ───
    "scheduled-fetch-quotes": {
        "task": "worker.tasks.quotes.scheduled_fetch_quotes",
        "schedule": crontab(hour=12, minute=40, day_of_week="1-5"),
        "options": {"queue": "io_queue"},
    },

    # ─── Retry stuck extractions (every 5 min) ───
    "retry-stuck-extractions": {
        "task": "worker.tasks.extraction.retry_stuck_extractions",
        "schedule": 300.0,
        "options": {"queue": "cpu_queue"},
    },

    # ─── Retry stuck concall extractions (every 2 min) ───
    "retry-stuck-concall": {
        "task": "worker.tasks.concall.retry_stuck_concall_extractions",
        "schedule": 120.0,
        "options": {"queue": "cpu_queue"},
    },

    # ─── Retry stuck announcement extractions (every 2 min) ───
    "retry-stuck-announcements": {
        "task": "worker.tasks.announcement_insight.retry_stuck_announcement_extractions",
        "schedule": 120.0,
        "options": {"queue": "cpu_queue"},
    },
}
