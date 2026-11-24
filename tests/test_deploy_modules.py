"""
The modules only deployed containers load: the production and CI settings, the WSGI entry point,
logging and Sentry. Settings modules are imported fresh with a controlled environment; nothing
here reconfigures the running Django.
"""

import importlib
import logging
import sys
from collections.abc import Callable
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from django.core.handlers.wsgi import WSGIHandler

from config import sentry
from config.logging import JsonFormatter

SETTINGS_MODULES = ["config.settings.production", "config.settings.ci", "config.settings.local"]


@pytest.fixture
def production_env() -> dict[str, str]:
    return {
        "SECRET_KEY": "s",
        "DJANGO_ALLOWED_HOSTS": "diagnostics.example",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://diagnostics.example,",
        "DATABASE_URL": "postgres://app:pw@db.internal:5432/diagnostics",
        "OCPP_DATABASE_URL": "postgres://readonly:pw@ocpp.internal:5432/ocpp",
        "OCPP_TENANTS": "public, eosgie",
    }


@pytest.fixture
def fresh_import(
    monkeypatch: pytest.MonkeyPatch, production_env: dict[str, str]
) -> Iterator[Callable[..., ModuleType]]:
    """Import a settings module from scratch with the production environment (plus extras)."""
    local = sys.modules["config.settings.local"]

    def load(name: str, drop: tuple[str, ...] = (), **extra_env: str) -> ModuleType:
        for key in ("SENTRY_DSN", "DATABASE_URL"):
            monkeypatch.delenv(key, raising=False)
        for key, value in {**production_env, **extra_env}.items():
            monkeypatch.setenv(key, value)
        for key in drop:
            monkeypatch.delenv(key, raising=False)
        for module in SETTINGS_MODULES:
            sys.modules.pop(module, None)
        return importlib.import_module(name)

    yield load
    for module in SETTINGS_MODULES:
        sys.modules.pop(module, None)
    sys.modules["config.settings.local"] = local


def test_production_settings_come_from_the_environment(
    fresh_import: Callable[..., ModuleType],
) -> None:
    prod = fresh_import("config.settings.production")

    assert prod.DEBUG is False and prod.SECRET_KEY == "s"
    assert prod.ALLOWED_HOSTS == ["diagnostics.example"]
    assert prod.CSRF_TRUSTED_ORIGINS == ["https://diagnostics.example"]  # empty items dropped
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE and prod.SECURE_SSL_REDIRECT
    assert prod.DATABASES["default"]["HOST"] == "db.internal"


def test_production_settings_api_ocpp_is_read_only_per_tenant(
    fresh_import: Callable[..., ModuleType],
) -> None:
    prod = fresh_import("config.settings.production")

    assert prod.OCPP_TENANTS == ["public", "eosgie"]
    eosgie = prod.DATABASES["ocpp_eosgie"]
    assert (eosgie["HOST"], eosgie["NAME"], eosgie["USER"]) == (
        "ocpp.internal",
        "ocpp",
        "readonly",
    )
    assert eosgie["OPTIONS"]["options"] == (
        "-c search_path=eosgie -c default_transaction_read_only=on"
    )


def test_production_settings_gateway_and_gireve_are_optional_and_read_only(
    fresh_import: Callable[..., ModuleType],
) -> None:
    prod = fresh_import(
        "config.settings.production",
        drop=("GIREVE_DATABASE_URL",),
        GATEWAY_DATABASE_URL="postgres://readonly:pw@gateway.internal:5432/gateway",
    )

    assert prod.DATABASES["gateway"]["HOST"] == "gateway.internal"
    assert prod.DATABASES["gateway"]["OPTIONS"] == {
        "options": "-c default_transaction_read_only=on"
    }
    assert "gireve" not in prod.DATABASES


@pytest.mark.parametrize(
    "missing",
    [
        "SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
        "OCPP_DATABASE_URL",
        "OCPP_TENANTS",
    ],
)
def test_production_settings_require_their_secrets(
    fresh_import: Callable[..., ModuleType], missing: str
) -> None:
    with pytest.raises(KeyError, match=missing):
        fresh_import("config.settings.production", drop=(missing,))


def test_ci_settings_give_each_tenant_its_test_database(
    fresh_import: Callable[..., ModuleType],
) -> None:
    ci = fresh_import("config.settings.ci", drop=("OCPP_DATABASE_URL", "OCPP_TENANTS"))

    assert ci.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert ci.DATABASES["ocpp_eosgie"]["TEST"] == {"NAME": "test_ocpp_eosgie"}
    assert ci.DATABASES["ocpp_eosgie"]["OPTIONS"] == {"options": "-c search_path=eosgie,public"}
    assert ci.DATABASES["gireve"]["TEST"] == {"NAME": "test_gireve"}


def test_local_settings_use_a_real_api_ocpp_when_given_one(
    fresh_import: Callable[..., ModuleType],
) -> None:
    local = fresh_import("config.settings.local")

    assert local.DATABASES["ocpp_public"]["HOST"] == "ocpp.internal"
    assert (
        "default_transaction_read_only=on" in local.DATABASES["ocpp_public"]["OPTIONS"]["options"]
    )


def test_local_settings_gateway_and_gireve_real_or_sqlite(
    fresh_import: Callable[..., ModuleType],
) -> None:
    local = fresh_import(
        "config.settings.local",
        drop=("GIREVE_DATABASE_URL",),
        GATEWAY_DATABASE_URL="postgres://readonly:pw@gateway.internal:5432/gateway",
    )

    assert local.DATABASES["gateway"]["HOST"] == "gateway.internal"
    assert "default_transaction_read_only=on" in local.DATABASES["gateway"]["OPTIONS"]["options"]
    assert local.DATABASES["gireve"]["ENGINE"] == "django.db.backends.sqlite3"


def test_wsgi_exposes_an_application() -> None:
    sys.modules.pop("config.wsgi", None)

    assert isinstance(importlib.import_module("config.wsgi").application, WSGIHandler)


@pytest.fixture
def log_record() -> logging.LogRecord:
    return logging.LogRecord(
        "diagnostics", logging.ERROR, __file__, 1, "charger %s", ("CP1",), None
    )


def test_json_formatter_writes_one_object(log_record: logging.LogRecord) -> None:
    line = JsonFormatter().format(log_record)

    assert '"message": "charger CP1"' in line and '"level": "ERROR"' in line


def test_json_formatter_includes_the_exception(log_record: logging.LogRecord) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        log_record.exc_info = sys.exc_info()

    assert "ValueError: boom" in JsonFormatter().format(log_record)


@pytest.fixture
def sentry_init(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry.sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    return calls


def test_sentry_off_without_dsn(
    monkeypatch: pytest.MonkeyPatch, sentry_init: list[dict[str, Any]]
) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    sentry.init_sentry()

    assert sentry_init == []


def test_sentry_on_with_dsn(
    monkeypatch: pytest.MonkeyPatch, sentry_init: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example/1")
    monkeypatch.setenv("IMAGE_TAG", "v1.2.0")

    sentry.init_sentry()

    assert sentry_init[0]["release"] == "v1.2.0"
    assert sentry_init[0]["send_default_pii"] is False
