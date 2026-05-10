"""
Sentry integration for error tracking.
Initialize once at app startup. Set SENTRY_DSN env var to enable.
"""

import os
import logging

logger = logging.getLogger(__name__)


def init_sentry():
    """Initialize Sentry SDK if SENTRY_DSN is set."""
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info("Sentry: disabled (SENTRY_DSN not set)")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            release=os.getenv("APP_VERSION", "1.0.0"),
            traces_sample_rate=0.1,  # 10% of transactions
            profiles_sample_rate=0.05,  # 5% profiling
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                RedisIntegration(),
                CeleryIntegration(),
            ],
            before_send=_before_send,
        )
        logger.info(f"Sentry: initialized (env={os.getenv('ENVIRONMENT', 'production')})")
    except ImportError:
        logger.warning("Sentry: sentry-sdk not installed, skipping")
    except Exception as e:
        logger.error(f"Sentry: init failed — {e}")


def _before_send(event, hint):
    """Filter out noisy errors before sending to Sentry."""
    if "exc_info" in hint:
        exc_type, exc_value, _ = hint["exc_info"]
        # Don't send expected client errors
        if exc_type.__name__ in ("WebSocketDisconnect", "ConnectionResetError"):
            return None
    return event
