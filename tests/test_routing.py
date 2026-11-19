import pytest
from django.db.models import Model
from django.test import Client
from django.urls import reverse

from config.routers import ServiceRouter
from diagnostics.models import Case
from services.gateway.models import Evse
from services.gireve.models import CPOToken
from services.ocpp.models import ChargePointV16
from services.ocpp.models import ConnectorV16


def test_router_reads_ocpp_from_first_tenant() -> None:
    assert ServiceRouter().db_for_read(ChargePointV16) == "ocpp_public"


@pytest.mark.parametrize("model", [Evse, CPOToken], ids=lambda model: model._meta.app_label)
def test_router_reads_single_database_services_from_their_alias(model: type[Model]) -> None:
    assert ServiceRouter().db_for_read(model) == model._meta.app_label


@pytest.mark.parametrize("db_alias", ["default", "ocpp_public", "gateway", "gireve"])
@pytest.mark.parametrize("app_label", ["ocpp", "gateway", "gireve"])
def test_router_never_migrates_the_services(db_alias: str, app_label: str) -> None:
    assert ServiceRouter().allow_migrate(db_alias, app_label) is False


def test_router_migrates_own_tables_on_default_only() -> None:
    router = ServiceRouter()

    assert router.allow_migrate("default", "diagnostics") is True
    assert router.allow_migrate("ocpp_public", "diagnostics") is False


def test_router_relates_api_ocpp_objects_across_tenant_aliases() -> None:
    assert ServiceRouter().allow_relation(ConnectorV16(), ChargePointV16()) is True


def test_router_leaves_other_relations_to_django() -> None:
    assert ServiceRouter().allow_relation(Case(), ChargePointV16()) is None


def test_healthz(client: Client) -> None:
    assert client.get(reverse("healthz")).json() == {"status": "ok"}
