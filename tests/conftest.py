"""
pytest-django setup and shared fixtures.

Tests run on SQLite with the local settings: that's the local run. CI also runs them on Postgres
with DJANGO_SETTINGS_MODULE=config.settings.ci, where coverage must be 100%. Tests marked
`postgres` need Postgres (introspection of its catalogs) and are skipped on SQLite.

api-ocpp's tables are created once per test session in every tenant's test database, from the
generated models (the `ocpp_tables` fixture), so the snapshot queries run against real tables on
both backends.
"""

import uuid
from collections.abc import Callable
from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connections
from django.db.models import Model
from django.test import Client

from config.roles import set_roles
from deployments.github import WorkflowRun
from deployments.kube import Rollout
from deployments.registry import PRODUCTION
from deployments.registry import SERVICES
from deployments.status import EnvironmentStatus
from deployments.status import KubeResult
from diagnostics.assistant import Assessment
from diagnostics.snapshot import Snapshot
from diagnostics.snapshot import ocpp_alias
from services.ocpp.models import ChargePointV16
from services.ocpp.models import ConnectorV16
from services.ocpp.models import FirmwareV16
from services.ocpp.models import Incident
from services.ocpp.models import Maintenance
from services.ocpp.models import RejectedRfid
from services.ocpp.models import TransactionV16


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    no_pg = not settings.DATABASES["default"]["ENGINE"].endswith("postgresql")
    skip_pg = pytest.mark.skip(reason="Postgres-only; run with config.settings.ci")
    for item in items:
        if no_pg and "postgres" in item.keywords:  # pragma: no cover  (only on SQLite)
            item.add_marker(skip_pg)


@pytest.fixture(scope="session")
def ocpp_tables(django_db_setup: None, django_db_blocker: Any) -> None:
    """Create api-ocpp's tables in each tenant's test database, as api-ocpp's Alembic would.

    Requested only by tests marked `django_db(databases="__all__")`: pytest-django sets up the
    tenants' test databases only when such a test is collected, and the aliases would otherwise
    point at the configured databases.
    """
    with django_db_blocker.unblock():
        for tenant in settings.OCPP_TENANTS:
            connection = connections[ocpp_alias(tenant)]
            if connection.vendor == "postgresql":  # pragma: no branch  (SQLite has no schemas)
                with connection.cursor() as cursor:
                    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{tenant}"')
            with connection.schema_editor() as editor:
                for model in apps.get_app_config("ocpp").get_models():
                    editor.create_model(model)


@pytest.fixture(scope="session")
def service_tables(django_db_setup: None, django_db_blocker: Any) -> None:
    """Create api-gateway's and api-gireve's tables in their test databases, as create_all would.

    Like ocpp_tables, only for tests marked `django_db(databases="__all__")`.
    """
    with django_db_blocker.unblock():
        for service in settings.SERVICE_DATABASES:
            with connections[service].schema_editor() as editor:
                for model in apps.get_app_config(service).get_models():
                    editor.create_model(model)


@pytest.fixture
def tenants() -> list[str]:
    return list(settings.OCPP_TENANTS)


@pytest.fixture
def save(ocpp_tables: None) -> Callable[[str, Model], Model]:
    """Insert an instance into a tenant's api-ocpp test database.

    Tests using it need `pytest.mark.django_db(databases="__all__")`.
    """

    def insert(tenant: str, instance: Model) -> Model:
        instance.save(using=ocpp_alias(tenant), force_insert=True)
        return instance

    return insert


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def make_charge_point(now: datetime) -> Callable[..., ChargePointV16]:
    def factory(**overrides: Any) -> ChargePointV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "identity": "FR*SWI*CP001",
            "charger_name": "Parking level -1",
            "customer_name": "ACME",
            "charger_type": "PUBLIC",
            "ocpp_version": "OcppV16",
            "is_active": True,
            "connected": True,
            "last_heartbeat": now - timedelta(seconds=20),
            "availability": "operative",
            "status": "available",
            "iccid": "8933",
            "super_charger": False,
            "is_plug_and_charge": False,
            "is_double_authentication": False,
            "availability_rating_enabled": False,
        }
        return ChargePointV16(**(values | overrides))

    return factory


@pytest.fixture
def make_connector(now: datetime) -> Callable[..., ConnectorV16]:
    def factory(**overrides: Any) -> ConnectorV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "index": 1,
            "status": "available",
            "error_code": "no_error",
            "availability": "operative",
            "connected": True,
            "updated_at": now - timedelta(minutes=1),
        }
        return ConnectorV16(**(values | overrides))

    return factory


@pytest.fixture
def make_transaction(now: datetime) -> Callable[..., TransactionV16]:
    def factory(**overrides: Any) -> TransactionV16:
        values: dict[str, Any] = {
            "id": 1234,
            "uid": uuid.uuid4(),
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "work_place": "PUBLIC",
            "status": "FINISHED",
            "id_tag": "BADGE1",
            "created_at": now - timedelta(hours=2),
            "started_at": now - timedelta(hours=2),
            "ended_at": now - timedelta(hours=1),
            "energy_delivered": 12000.0,
            "reason": "local",
        }
        return TransactionV16(**(values | overrides))

    return factory


@pytest.fixture
def make_incident(now: datetime) -> Callable[..., Incident]:
    def factory(**overrides: Any) -> Incident:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "event": "disconnected",
            "identity": "FR*SWI*CP001",
            "started_at": now,
        }
        return Incident(**(values | overrides))

    return factory


@pytest.fixture
def make_rejection(now: datetime) -> Callable[..., RejectedRfid]:
    def factory(**overrides: Any) -> RejectedRfid:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "id_token": "BADGE9",
            "reason_kind": "RFID_DOES_NOT_EXIST",
            "identity": "FR*SWI*CP001",
            "created_at": now - timedelta(minutes=30),
        }
        return RejectedRfid(**(values | overrides))

    return factory


@pytest.fixture
def make_maintenance(now: datetime) -> Callable[..., Maintenance]:
    def factory(**overrides: Any) -> Maintenance:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "identity": "FR*SWI*CP001",
            "maintainer": "Technician",
            "reason": "Replaced the RFID reader",
            "maintenance_at": now - timedelta(hours=3),
        }
        return Maintenance(**(values | overrides))

    return factory


@pytest.fixture
def make_firmware(now: datetime) -> Callable[..., FirmwareV16]:
    def factory(**overrides: Any) -> FirmwareV16:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "status": "installed",
            "firmware_version": "2.1.0",
            "created_at": now - timedelta(hours=1),
            "updated_at": now - timedelta(minutes=50),
        }
        return FirmwareV16(**(values | overrides))

    return factory


@pytest.fixture
def make_snapshot(
    make_charge_point: Callable[..., ChargePointV16], make_connector: Callable[..., ConnectorV16]
) -> Callable[..., Snapshot]:
    def factory(**overrides: Any) -> Snapshot:
        values: dict[str, Any] = {
            "tenant": "public",
            "charge_point": make_charge_point(),
            "connectors": [make_connector()],
        }
        return Snapshot(**(values | overrides))

    return factory


@pytest.fixture
def admin_client(db: None) -> Client:
    user = User.objects.create_superuser("support", "support@example.com", "password")
    client = Client()
    # The password backend, as locally: a proxy session without the proxy's headers is signed out.
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return client


@pytest.fixture
def make_client(db: None) -> Callable[..., Client]:
    """A signed-in staff user with exactly these roles (none: a staff user with no role)."""

    def factory(*roles: str, username: str = "ana@swish.example") -> Client:
        user = User.objects.create_user(username, is_staff=True)
        set_roles(user, set(roles))
        client = Client()
        client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        return client

    return factory


@pytest.fixture
def proxy_headers() -> dict[str, str]:
    """What the auth proxy forwards for a member of the support group."""
    return {
        "HTTP_X_FORWARDED_USER": "ana@swish.example",
        "HTTP_X_FORWARDED_GROUPS": "eng, swish-support",
    }


@pytest.fixture
def proxy_secret(settings: Any) -> Iterator[dict[str, str]]:
    settings.AUTH_PROXY = {**settings.AUTH_PROXY, "PROXY_SECRET": "s3cret"}
    yield {"HTTP_X_PROXY_SECRET": "s3cret"}


# --- Deployments ---


@pytest.fixture
def make_run(now: datetime) -> Callable[..., WorkflowRun]:
    def factory(**overrides: Any) -> WorkflowRun:
        values: dict[str, Any] = {
            "run_number": 42,
            "status": "completed",
            "conclusion": "success",
            "head_sha": "0123456789abcdef",
            "commit_message": "Merge pull request #1",
            "actor": "dev",
            "html_url": "https://github.com/swish-charge/api-ocpp/actions/runs/1",
            "run_started_at": now - timedelta(minutes=10),
            "updated_at": now - timedelta(minutes=5),
        }
        return WorkflowRun(**(values | overrides))

    return factory


@pytest.fixture
def make_rollout(now: datetime) -> Callable[..., Rollout]:
    def factory(**overrides: Any) -> Rollout:
        values: dict[str, Any] = {
            "cluster": "production",
            "namespace": "ocpp-api",
            "deployment": "ocpp-api",
            "desired": 4,
            "ready": 4,
            "updated": 4,
            "available": 4,
            "image": "swishacr098e18.azurecr.io/ocpp-api:main",
            "restarted_at": now - timedelta(minutes=6),
            "pod_restarts": 0,
            "progress_message": "",
        }
        return Rollout(**(values | overrides))

    return factory


@pytest.fixture
def make_status() -> Callable[..., EnvironmentStatus]:
    def factory(run: WorkflowRun | None, rollouts: list[Rollout | None]) -> EnvironmentStatus:
        kube = [
            KubeResult(
                "production", "ns", "dep", rollout=rollout, error="" if rollout else "unreachable"
            )
            for rollout in rollouts
        ]
        return EnvironmentStatus(service=SERVICES[0], environment=PRODUCTION, run=run, kube=kube)

    return factory


# --- Claude's assessment ---


@pytest.fixture
def make_assessment() -> Callable[..., Assessment]:
    def factory(**overrides: Any) -> Assessment:
        values: dict[str, Any] = {
            "assessment": "The charger has been offline since 10:02 and has no power.",
            "likely_cause": "Power cut on site",
            "confidence": "high",
            "agrees_with_rules": True,
            "support_steps": ["Ask the site to check the breaker."],
            "customer_reply": "The charger has no power; the site is checking it.",
            "needs_escalation": True,
            "ticket_title": "EOS-1 offline without power",
            "ticket_description": "Offline since 10:02.\nNo power on site.",
        }
        return Assessment(**(values | overrides))

    return factory
