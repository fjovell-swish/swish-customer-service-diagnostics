from collections.abc import Callable
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from config.routers import ServiceRouter
from diagnostics import views
from diagnostics.snapshot import ChargerMatch
from diagnostics.snapshot import Snapshot
from services.ocpp.models import ChargePointV16


@pytest.fixture
def stub_lookup(monkeypatch: pytest.MonkeyPatch, make_snapshot: Callable[..., Snapshot]) -> Callable[..., None]:
    def install(matches: list[ChargerMatch]) -> None:
        monkeypatch.setattr(views, "find_chargers", lambda query: matches)
        monkeypatch.setattr(
            views,
            "collect",
            lambda tenant, charge_point, now: make_snapshot(tenant=tenant, charge_point=charge_point),
        )

    return install


def test_diagnose_requires_login(client: Client, db: None) -> None:
    response = client.get(reverse("diagnose"))

    assert response.status_code == HTTPStatus.FOUND
    assert "/admin/login/" in response.url


def test_diagnose_empty_search(admin_client: Client) -> None:
    response = admin_client.get(reverse("diagnose"))

    assert response.status_code == HTTPStatus.OK
    assert b"Charger identity, name or serial number" in response.content


def test_diagnose_no_match(admin_client: Client, stub_lookup: Callable[..., None]) -> None:
    stub_lookup([])

    response = admin_client.get(reverse("diagnose"), {"q": "nope"})

    assert b"No charger matches" in response.content


def test_diagnose_several_matches_lists_them(
    admin_client: Client, stub_lookup: Callable[..., None], make_charge_point: Callable[..., ChargePointV16]
) -> None:
    stub_lookup([ChargerMatch("public", make_charge_point()), ChargerMatch("eosgie", make_charge_point())])

    response = admin_client.get(reverse("diagnose"), {"q": "CP001"})

    assert b"2 chargers match" in response.content
    assert b"tenant=eosgie" in response.content


def test_diagnose_tenant_narrows_matches(
    admin_client: Client, stub_lookup: Callable[..., None], make_charge_point: Callable[..., ChargePointV16]
) -> None:
    stub_lookup([ChargerMatch("public", make_charge_point()), ChargerMatch("eosgie", make_charge_point())])

    response = admin_client.get(reverse("diagnose"), {"q": "CP001", "tenant": "eosgie"})

    assert response.context["snapshot"].tenant == "eosgie"


def test_diagnose_single_match_shows_findings(
    admin_client: Client, stub_lookup: Callable[..., None], make_charge_point: Callable[..., ChargePointV16]
) -> None:
    stub_lookup([ChargerMatch("public", make_charge_point(connected=False))])

    response = admin_client.get(reverse("diagnose"), {"q": "FR*SWI*CP001"})

    assert response.status_code == HTTPStatus.OK
    assert b"Charger offline" in response.content
    assert b"copy-reply" in response.content


def test_router_reads_ocpp_from_first_tenant() -> None:
    assert ServiceRouter().db_for_read(ChargePointV16) == "ocpp_public"


@pytest.mark.parametrize("db_alias", ["default", "ocpp_public"])
def test_router_never_migrates_ocpp(db_alias: str) -> None:
    assert ServiceRouter().allow_migrate(db_alias, "ocpp") is False


def test_router_migrates_own_tables_on_default_only() -> None:
    router = ServiceRouter()

    assert router.allow_migrate("default", "auth") is True
    assert router.allow_migrate("ocpp_public", "auth") is False


def test_healthcheck(client: Client) -> None:
    assert client.get(reverse("healthcheck")).json() == {"status": "ok"}
