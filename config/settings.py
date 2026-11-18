import os
from pathlib import Path
from typing import Any

import dj_database_url
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = env_bool("DEBUG", False)
ENVIRONMENT = os.getenv("ENVIRONMENT", "local")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # The admin is only used for login and managing support users.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "services.ocpp",
    "diagnostics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Databases -------------------------------------------------------------------------------
# `default` holds only this app's own tables (users, sessions). api-ocpp is read through
# unmanaged models over read-only connections: this tool never writes to a service database.

DATABASES: dict[str, dict[str, Any]] = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
    ),
}


def service_database(url: str, search_path: str) -> dict[str, Any]:
    config = dj_database_url.parse(url, conn_max_age=600, conn_health_checks=True)
    config.setdefault("OPTIONS", {})["options"] = f"-c search_path={search_path} -c default_transaction_read_only=on"
    return config


# api-ocpp keeps one Postgres schema per tenant, so every tenant gets its own alias ("ocpp_<tenant>").
# A charger lookup searches all of them, since support rarely knows the tenant.
OCPP_TENANTS = env_list("OCPP_TENANTS", "public")
OCPP_DATABASE_URL = os.environ["OCPP_DATABASE_URL"]
for tenant in OCPP_TENANTS:
    DATABASES[f"ocpp_{tenant}"] = service_database(OCPP_DATABASE_URL, search_path=tenant)

DATABASE_ROUTERS = ["config.routers.ServiceRouter"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Misc ------------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, environment=ENVIRONMENT, integrations=[DjangoIntegration()])
