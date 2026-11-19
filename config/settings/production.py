"""
Production (and every deployed environment, staging included): DEBUG off, every value from the
environment. wsgi.py defaults to this module.

Required: SECRET_KEY, DJANGO_ALLOWED_HOSTS, AUTH_PROXY_SECRET, DATABASE_URL (this app's own
Postgres: cases and users), OCPP_DATABASE_URL (a read-only user on api-ocpp's database),
OCPP_TENANTS (api-ocpp's TENANT_SCHEMAS, comma-separated).
Optional: DJANGO_CSRF_TRUSTED_ORIGINS, AUTH_PROXY_* header names and groups (settings/base.py),
SENTRY_DSN, SENTRY_TRACES_SAMPLE_RATE, ENVIRONMENT, IMAGE_TAG, LOG_LEVEL, LOG_FORMAT.
"""

import os
from typing import Any

import dj_database_url

from config.sentry import init_sentry
from config.settings.base import AUTH_PROXY
from config.settings.base import *  # noqa: F401,F403
from config.settings.base import ocpp_databases

DEBUG = False
SECRET_KEY = os.environ["SECRET_KEY"]
ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
# The platform's liveness/readiness probes call the container over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# Preloading commits the whole domain to HTTPS in browsers for good: a decision for the domain's
# owners, not this app.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

OCPP_TENANTS = [tenant.strip() for tenant in os.environ["OCPP_TENANTS"].split(",")]

# Required: without it anyone reaching the container could send the identity headers.
AUTH_PROXY = {**AUTH_PROXY, "PROXY_SECRET": os.environ["AUTH_PROXY_SECRET"]}

DATABASES: dict[str, dict[str, Any]] = {
    "default": dict(
        dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60, conn_health_checks=True)
    ),
    # Read-only twice over: the database user should only have SELECT, and every transaction is
    # read-only, so nothing in this app can write to api-ocpp by accident.
    **ocpp_databases(os.environ["OCPP_DATABASE_URL"], OCPP_TENANTS, read_only=True),
}

init_sentry()
