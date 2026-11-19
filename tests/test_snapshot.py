"""The api-ocpp queries, against api-ocpp's tables in every tenant's test database."""

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta

import pytest
from django.db.models import Model

from diagnostics.snapshot import LOOKBACK
from diagnostics.snapshot import collect
from diagnostics.snapshot import find_chargers
from services.ocpp.models import ChargePointV16

pytestmark = [pytest.mark.django_db(databases="__all__"), pytest.mark.usefixtures("ocpp_tables")]


@pytest.fixture
def public(tenants: list[str]) -> str:
    return tenants[0]


@pytest.fixture
def other_tenant(tenants: list[str]) -> str:
    return tenants[1]


@pytest.fixture
def charge_point(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    public: str,
) -> Model:
    return save(public, make_charge_point())


def test_find_chargers_exact_identity(charge_point: ChargePointV16, public: str) -> None:
    matches = find_chargers(" FR*SWI*CP001 ")

    assert [(match.tenant, match.charge_point.id) for match in matches] == [
        (public, charge_point.id)
    ]


def test_find_chargers_blank_query(charge_point: ChargePointV16) -> None:
    assert find_chargers("   ") == []


@pytest.mark.parametrize("query", ["swi*cp", "level -1", "SN-77", "BOX-42"])
def test_find_chargers_fragments(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    public: str,
    query: str,
) -> None:
    save(public, make_charge_point(serial_number="SN-77", charge_box_serial_number="BOX-42"))

    assert len(find_chargers(query)) == 1


def test_find_chargers_searches_every_tenant(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    public: str,
    other_tenant: str,
) -> None:
    save(public, make_charge_point(identity="CP-A1"))
    save(other_tenant, make_charge_point(identity="CP-A2"))

    assert sorted(match.tenant for match in find_chargers("CP-A")) == sorted(
        [public, other_tenant]
    )


def test_find_chargers_exact_identity_beats_fragments_elsewhere(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    public: str,
    other_tenant: str,
) -> None:
    save(public, make_charge_point(identity="CP-7"))
    save(other_tenant, make_charge_point(identity="CP-77"))

    assert [match.tenant for match in find_chargers("CP-7")] == [public]


def test_collect_reads_everything_about_the_charger(
    save: Callable[[str, Model], Model],
    charge_point: ChargePointV16,
    public: str,
    now: datetime,
    make_connector: Callable[..., Model],
    make_transaction: Callable[..., Model],
    make_incident: Callable[..., Model],
    make_rejection: Callable[..., Model],
    make_maintenance: Callable[..., Model],
    make_firmware: Callable[..., Model],
) -> None:
    connector = save(public, make_connector(charge_point=charge_point))
    save(public, make_transaction(connector=connector))
    save(public, make_incident())
    save(public, make_rejection())
    save(public, make_maintenance())
    save(public, make_firmware(charge_point=charge_point))

    snapshot = collect(public, charge_point, now)

    assert snapshot.tenant == public
    assert [c.id for c in snapshot.connectors] == [connector.pk]
    assert len(snapshot.transactions) == 1
    assert len(snapshot.incidents) == 1
    assert len(snapshot.rejected_rfids) == 1
    assert len(snapshot.maintenances) == 1
    assert len(snapshot.firmwares) == 1


def test_collect_leaves_out_what_is_older_than_the_lookback(
    save: Callable[[str, Model], Model],
    charge_point: ChargePointV16,
    public: str,
    now: datetime,
    make_connector: Callable[..., Model],
    make_transaction: Callable[..., Model],
    make_incident: Callable[..., Model],
    make_rejection: Callable[..., Model],
) -> None:
    old = now - LOOKBACK - timedelta(hours=1)
    connector = save(public, make_connector(charge_point=charge_point))
    save(public, make_transaction(connector=connector, created_at=old))
    save(public, make_incident(started_at=old))
    save(public, make_rejection(created_at=old))

    snapshot = collect(public, charge_point, now)

    assert (snapshot.transactions, snapshot.incidents, snapshot.rejected_rfids) == ([], [], [])


def test_collect_keeps_old_open_transactions(
    save: Callable[[str, Model], Model],
    charge_point: ChargePointV16,
    public: str,
    now: datetime,
    make_connector: Callable[..., Model],
    make_transaction: Callable[..., Model],
) -> None:
    connector = save(public, make_connector(charge_point=charge_point))
    save(
        public,
        make_transaction(
            connector=connector, status="ONGOING", created_at=now - timedelta(days=5)
        ),
    )

    assert [t.status for t in collect(public, charge_point, now).transactions] == ["ONGOING"]


def test_collect_ignores_other_chargers(
    save: Callable[[str, Model], Model],
    charge_point: ChargePointV16,
    public: str,
    now: datetime,
    make_charge_point: Callable[..., ChargePointV16],
    make_connector: Callable[..., Model],
    make_incident: Callable[..., Model],
) -> None:
    other = save(public, make_charge_point(identity="OTHER"))
    save(public, make_connector(charge_point=other))
    save(public, make_incident(identity="OTHER"))

    snapshot = collect(public, charge_point, now)

    assert (snapshot.connectors, snapshot.incidents) == ([], [])
