"""
Local development and tests: SQLite, DEBUG on, everything hard-coded so `manage.py` and `pytest`
run with no environment. `manage.py` defaults to this module.

api-ocpp: set OCPP_DATABASE_URL (and OCPP_TENANTS) to look at a real environment, read-only.
Without it each tenant is an empty local SQLite file; tests create api-ocpp's tables in memory.
"""

import os

from config.settings.base import BASE_DIR
from config.settings.base import PGBOUNCER
from config.settings.base import SERVICE_DATABASES
from config.settings.base import *  # noqa: F401,F403
from config.settings.base import env_list
from config.settings.base import ocpp_databases
from config.settings.base import service_database

DEBUG = True
SECRET_KEY = "local-dev-only-not-a-secret"
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# No manifest storage locally/in tests: pages work without running collectstatic first.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Locally there is no proxy: `manage.py createsuperuser` and the admin login form work too.
AUTHENTICATION_BACKENDS = [
    "config.auth_proxy.GroupRemoteUserBackend",
    "django.contrib.auth.backends.ModelBackend",
]

OCPP_TENANTS = env_list("OCPP_TENANTS", "public,eosgie")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "local.sqlite3",
        # Tests use a private in-memory database (per process, so per pytest-xdist worker).
        "TEST": {"NAME": ":memory:"},
    },
}
if os.environ.get("OCPP_DATABASE_URL"):
    DATABASES |= ocpp_databases(
        os.environ["OCPP_DATABASE_URL"], OCPP_TENANTS, read_only=True, pgbouncer=PGBOUNCER
    )
else:
    for tenant in OCPP_TENANTS:
        DATABASES[f"ocpp_{tenant}"] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / f"local_ocpp_{tenant}.sqlite3",
            "TEST": {"NAME": ":memory:"},
        }

for service in SERVICE_DATABASES:
    url = os.environ.get(f"{service.upper()}_DATABASE_URL")
    if url:
        DATABASES[service] = service_database(url, read_only=True, pgbouncer=PGBOUNCER)
    else:
        DATABASES[service] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / f"local_{service}.sqlite3",
            "TEST": {"NAME": ":memory:"},
        }
