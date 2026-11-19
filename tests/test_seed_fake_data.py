"""seed_fake_data: fills the local tenants, again and again, and never a real api-ocpp."""

from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from diagnostics.checks import run_checks
from diagnostics.snapshot import collect
from diagnostics.snapshot import find_chargers
from diagnostics.snapshot import ocpp_alias
from services.ocpp.management.commands import seed_fake_data
from services.ocpp.models import ChargePointV16

# The command recreates tables, which SQLite can't do inside a test's transaction.
pytestmark = [
    pytest.mark.django_db(databases="__all__", transaction=True),
    pytest.mark.usefixtures("ocpp_tables"),
]


@pytest.fixture
def local_tenants(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Seeding allowed whatever the backend (CI's Postgres too); empty tables afterwards."""
    monkeypatch.setattr(seed_fake_data, "is_local", lambda connection: True)
    yield
    for tenant in settings.OCPP_TENANTS:
        seed_fake_data.Command().reset_tables(connections[ocpp_alias(tenant)])


@pytest.fixture
def seed(local_tenants: None) -> str:
    out = StringIO()
    call_command("seed_fake_data", stdout=out)
    return out.getvalue()


def test_seed_fake_data_fills_every_tenant(seed: str, tenants: list[str]) -> None:
    counts = [ChargePointV16.objects.using(ocpp_alias(t)).count() for t in tenants]

    assert counts == [11, 2]
    assert f"{ocpp_alias(tenants[0])}: 11 fake chargers" in seed


def test_seed_fake_data_creates_the_support_user(seed: str) -> None:
    assert User.objects.get(username="support").check_password("support")
    assert "Created the user support / support" in seed


def test_seed_fake_data_runs_again(seed: str, tenants: list[str]) -> None:
    out = StringIO()

    call_command("seed_fake_data", stdout=out)

    assert ChargePointV16.objects.using(ocpp_alias(tenants[0])).count() == 11
    assert "Created the user" not in out.getvalue()


@pytest.mark.parametrize(
    ("identity", "finding"),
    [
        ("SEED-OK-01", None),
        ("SEED-OFFLINE-01", "Charger offline"),
        ("SEED-SILENT-01", "Connected but silent"),
        ("SEED-FLAKY-01", "Unstable connection"),
        ("SEED-FAULT-01", "Connector 1 faulted: ground_failure"),
        ("SEED-BADGE-01", "Badge BADGE-PRIVATE refused: PRIVATE_CHARGER"),
        ("SEED-CAR-01", "Connector 1: the car isn't taking power"),
        ("SEED-STUCK-01", "still open after 3 days"),
        ("SEED-INACTIVE-01", "Charger not activated"),
        ("SEED-OFFSERVICE-01", "Charger set to inoperative"),
        ("SEED-FIRMWARE-01", "Last firmware update download_failed"),
        ("SEED-TENANT-01", "Badge BADGE-EMSP refused: EMSP_REJECTION"),
        ("SEED-TENANT-02", "the charger is holding back power"),
    ],
)
def test_seed_fake_data_each_charger_shows_its_problem(
    seed: str, identity: str, finding: str | None
) -> None:
    [match] = find_chargers(identity)
    now = timezone.now()

    titles = [f.title for f in run_checks(collect(match.tenant, match.charge_point, now), now)]

    if finding is None:
        assert titles == ["Online"]
    else:
        assert any(finding in title for title in titles), titles


def test_seed_fake_data_refuses_a_real_api_ocpp(
    monkeypatch: pytest.MonkeyPatch, tenants: list[str]
) -> None:
    monkeypatch.setattr(seed_fake_data, "is_local", lambda connection: False)

    with pytest.raises(CommandError, match="Refusing to write"):
        call_command("seed_fake_data", stdout=StringIO())

    assert ChargePointV16.objects.using(ocpp_alias(tenants[0])).count() == 0


@pytest.mark.parametrize(("vendor", "local"), [("sqlite", True), ("postgresql", False)])
def test_is_local_only_for_sqlite(vendor: str, local: bool) -> None:
    connection = SimpleNamespace(vendor=vendor)

    assert seed_fake_data.is_local(connection) is local  # type: ignore[arg-type]


def test_seed_fake_data_creates_missing_tables(local_tenants: None, tenants: list[str]) -> None:
    """The first run on a fresh local SQLite file: api-ocpp's tables don't exist yet."""
    connection = connections[ocpp_alias(tenants[0])]
    with connection.schema_editor() as editor:
        editor.delete_model(ChargePointV16)

    call_command("seed_fake_data", stdout=StringIO())

    assert ChargePointV16.objects.using(ocpp_alias(tenants[0])).count() == 11
