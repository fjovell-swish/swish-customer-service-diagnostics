"""
Sentry setup. Imported by settings/production.py, so this module must not import Django models.
`init_sentry()` does nothing unless SENTRY_DSN is set. The Django integration captures unhandled
exceptions and ERROR logs.
"""

import logging
import os

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration


def init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "dev"),
        release=os.environ.get("IMAGE_TAG") or None,
        integrations=[
            DjangoIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
    )
