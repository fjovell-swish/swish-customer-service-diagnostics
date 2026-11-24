"""
Settings shared by every environment. Nothing here depends on the environment: no DEBUG, no
SECRET_KEY, no databases, no hosts. Those live in local.py, ci.py and production.py, which import
this module with `from config.settings.base import *`.
"""

import os
from pathlib import Path
from typing import Any

import dj_database_url
import django_stubs_ext

# Lets the generic forms used for type checking (QuerySet[M], ...) be written in code without
# breaking at runtime; django-stubs' documented approach.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # TLS ends at the ingress
USE_X_FORWARDED_HOST = True


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


INSTALLED_APPS = [
    # The admin is only used for its look and its login page (locally); no model is registered.
    "django.contrib.admin",
    # The models' and views' docstrings at /admin/doc/ (the header's "Documentation" link).
    "django.contrib.admindocs",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "services.ocpp",
    "services.gateway",
    "services.gireve",
    "diagnostics",
    "deployments",
    "mcp_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.auth_proxy.ProxyHeaderMiddleware",
    "config.tenancy.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Staff sign in to the user service at the auth proxy in front of this app; Django trusts the
# headers it forwards, only with the proxy's secret, and only for groups that grant a role
# (config/auth_proxy.py, config/roles.py). local.py adds the password login for development.
AUTHENTICATION_BACKENDS = ["config.auth_proxy.GroupRemoteUserBackend"]
AUTH_PROXY: dict[str, Any] = {
    "USER_HEADER": os.environ.get("AUTH_PROXY_USER_HEADER", "X-Forwarded-User"),
    "GROUPS_HEADER": os.environ.get("AUTH_PROXY_GROUPS_HEADER", "X-Forwarded-Groups"),
    # The user service's groups that grant each role (config/roles.py); anyone else is refused.
    "ROLE_GROUPS": {
        "data": env_list("AUTH_PROXY_DATA_GROUPS", "swish-data,swish-ops"),
        "support": env_list("AUTH_PROXY_SUPPORT_GROUPS", "swish-support,swish-ops"),
    },
    "PROXY_SECRET_HEADER": os.environ.get("AUTH_PROXY_SECRET_HEADER", "X-Proxy-Secret"),
    "PROXY_SECRET": "",
}
# Sessions live in the signed cookie: every replica serves every request without a shared database.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # templates/admin/base_site.html: the header's tenant switcher, over the admin's own.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.navigation",
            ],
        },
    },
]

# --- The services' databases through PgBouncer --------------------------------------------------
# PGBOUNCER=true when the service URLs point at PgBouncer in transaction pooling (Azure's, port
# 6432): their aliases then use config/pgbouncer, which pins each tenant's schema and the
# read-only mode per transaction instead of once per connection. The app's own database
# (`default`) isn't affected.
PGBOUNCER = os.environ.get("PGBOUNCER", "").lower() in {"1", "true", "yes"}
PGBOUNCER_ENGINE = "config.pgbouncer"


def through_pgbouncer(config: dict[str, Any], search_path: str | None, read_only: bool) -> None:
    config["ENGINE"] = PGBOUNCER_ENGINE
    # Server-side cursors need their transaction's connection for as long as they're read.
    config["DISABLE_SERVER_SIDE_CURSORS"] = True
    config["PIN"] = {"search_path": search_path, "read_only": read_only}


# --- api-ocpp -------------------------------------------------------------------------------
# api-ocpp keeps one Postgres schema per tenant, so every tenant gets its own alias
# ("ocpp_<tenant>"). A charger lookup searches all of them, since support rarely knows the tenant.
# Each environment builds the aliases with ocpp_databases().
OCPP_TENANTS = env_list("OCPP_TENANTS", "public")
DATABASE_ROUTERS = ["config.routers.ServiceRouter"]


def ocpp_databases(
    url: str,
    tenants: list[str],
    read_only: bool,
    test_names: bool = False,
    pgbouncer: bool = False,
) -> dict[str, dict[str, Any]]:
    """One alias per tenant on api-ocpp's database, pinned to that tenant's schema."""
    databases = {}
    for tenant in tenants:
        config: dict[str, Any] = dict(
            dj_database_url.parse(url, conn_max_age=60, conn_health_checks=True)
        )
        if pgbouncer:
            through_pgbouncer(config, tenant, read_only)
            databases[f"ocpp_{tenant}"] = config
            continue
        # In a fresh test database the tenant's schema doesn't exist yet, so Django's own
        # bookkeeping (django_migrations) goes to `public`; api-ocpp's tables go to the tenant.
        search_path = f"{tenant},public" if test_names else tenant
        options = [f"-c search_path={search_path}"]
        if read_only:
            options.append("-c default_transaction_read_only=on")
        config["OPTIONS"] = {"options": " ".join(options)}
        if test_names:
            # Every alias would otherwise create the same test database.
            config["TEST"] = {"NAME": f"test_ocpp_{tenant}"}
        databases[f"ocpp_{tenant}"] = config
    return databases


# --- api-gateway and api-gireve ----------------------------------------------------------------
# One database each, no tenants: the alias is the app label. Optional when deployed: a service
# without a database URL has no alias, and its tables stay out of the admin.
SERVICE_DATABASES = ("gateway", "gireve")


def service_database(
    url: str, read_only: bool, test_name: str = "", pgbouncer: bool = False
) -> dict[str, Any]:
    config: dict[str, Any] = dict(
        dj_database_url.parse(url, conn_max_age=60, conn_health_checks=True)
    )
    if pgbouncer:
        through_pgbouncer(config, None, read_only)
    elif read_only:
        config["OPTIONS"] = {"options": "-c default_transaction_read_only=on"}
    if test_name:
        config["TEST"] = {"NAME": test_name}
    return config


# --- Deployments page (deployments/) -----------------------------------------------------------
# GitHub: read access to Actions and contents of the service repos. Kubernetes: a kubeconfig file
# per cluster, matching the kubeconfig secrets the services' CI uses; a cluster without one shows
# as "unknown".
GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "swish-charge")
KUBECONFIGS: dict[str, str] = {
    cluster: path
    for cluster, path in {
        "staging": os.environ.get("KUBECONFIG_STAGING", ""),
        "production": os.environ.get("KUBECONFIG_PRODUCTION", ""),
        "csms-production": os.environ.get("KUBECONFIG_CSMS_PRODUCTION", ""),
    }.items()
    if path
}
DEPLOYMENT_STATUS_CACHE_SECONDS = int(os.environ.get("DEPLOYMENT_STATUS_CACHE_SECONDS", "60"))
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- Claude's assessment of a case (diagnostics/assistant.py) ----------------------------------
# Without a key the "Ask Claude" button is hidden.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# --- The MCP API (mcp_api/) -------------------------------------------------------------------
# The app's public URL: the OAuth server's issuer, and /mcp's resource URL, for MCP clients.
MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8000")
# Sign-in with Microsoft for MCP clients: an Entra ID app registration (web, single tenant) whose
# redirect URI is MCP_BASE_URL + /oauth/microsoft/callback. Unset: personal tokens only.
MICROSOFT_TENANT_ID = os.environ.get("MICROSOFT_TENANT_ID", "")
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "")

# --- Escalating a case to Jira (diagnostics/jira.py) -------------------------------------------
# Jira Cloud, basic auth with an API token. Without them the "Create Jira ticket" button is hidden.
JIRA_URL = os.environ.get("JIRA_URL", "https://swishforgood.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT = os.environ.get("JIRA_PROJECT", "ROT")
JIRA_ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "[System] Incident")
JIRA_LABELS = env_list("JIRA_LABELS", "jira_escalated,support-diagnostics")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Hashed, compressed files served by WhiteNoise after `collectstatic` (the image does it).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)-7s %(name)s %(message)s"},
        "json": {"()": "config.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": os.environ.get("LOG_FORMAT", "plain"),
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"level": "WARNING"},
        "django.request": {"level": "ERROR"},  # 5xx only: Django logs 4xx as WARNING
        "django.db.backends": {"level": "WARNING"},
        "django.security.DisallowedHost": {"level": "ERROR"},
        "gunicorn.access": {"level": "WARNING"},  # access log via --access-logfile is enough
        "psycopg": {"level": "WARNING"},
    },
}
