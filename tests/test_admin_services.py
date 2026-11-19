"""api-gateway's and api-gireve's tables in the admin: every one listed, read-only."""

import uuid
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus

import pytest
from django.contrib import admin
from django.db.models import Model
from django.test import Client
from django.urls import reverse

from config.roles import DATA
from config.roles import SUPPORT
from services.admin_registration import register_app_models
from services.gateway.models import Client as GatewayClient
from services.gateway.models import Evse
from services.gateway.models import Location
from services.gateway.models import PushNotificationDeviceLink
from services.gireve.models import CPOToken

pytestmark = [
    pytest.mark.django_db(databases="__all__"),
    pytest.mark.usefixtures("service_tables"),
]

SERVICE_MODELS = [
    model for model in admin.site._registry if model._meta.app_label in {"gateway", "gireve"}
]


@pytest.fixture
def data_client(make_client: Callable[..., Client]) -> Client:
    return make_client(DATA)


@pytest.fixture
def evse(now: datetime) -> Evse:
    """A gateway EVSE, whose location is referenced by its OCPI id (`id`, not the key)."""
    timestamps = {"created_at": now, "updated_at": now}
    client = GatewayClient.objects.create(id_db=uuid.uuid4(), name="ACME", **timestamps)
    location = Location.objects.create(
        id_db=uuid.uuid4(), record_id="LOC-1", client=client, **timestamps
    )
    return Evse.objects.create(
        id_db=uuid.uuid4(),
        evse_id="FR*SWI*E001",
        uid="E001",
        status="AVAILABLE",
        location=location,
        **timestamps,
    )


def test_admin_services_register_every_table_but_the_link_table() -> None:
    gateway = [model for model in SERVICE_MODELS if model._meta.app_label == "gateway"]

    assert len(gateway) == 15
    assert len(SERVICE_MODELS) - len(gateway) == 16
    assert PushNotificationDeviceLink not in admin.site._registry


@pytest.mark.parametrize("model", SERVICE_MODELS, ids=lambda model: model._meta.label)
def test_admin_services_every_table_lists_for_the_data_role(
    data_client: Client, model: type[Model]
) -> None:
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")

    assert data_client.get(url).status_code == HTTPStatus.OK


def test_admin_services_follow_foreign_keys_to_renamed_ids(
    data_client: Client, evse: Evse
) -> None:
    changelist = data_client.get(reverse("admin:gateway_evse_changelist"))
    page = data_client.get(reverse("admin:gateway_evse_change", args=[evse.pk]))

    assert b"FR*SWI*E001" in changelist.content
    location_page = reverse("admin:gateway_location_change", args=[evse.location.pk])
    assert page.status_code == HTTPStatus.OK
    assert location_page.encode() in page.content
    assert Evse.objects.get().location.record_id == "LOC-1"


def test_admin_services_read_only(admin_client: Client, evse: Evse) -> None:
    page = admin_client.get(reverse("admin:gateway_evse_change", args=[evse.pk]))

    assert b'name="_save"' not in page.content
    assert admin_client.get(reverse("admin:gateway_evse_add")).status_code == HTTPStatus.FORBIDDEN


def test_admin_services_hidden_from_the_support_role(make_client: Callable[..., Client]) -> None:
    support = make_client(SUPPORT)
    url = reverse("admin:gireve_cpotoken_changelist")

    assert support.get(url).status_code == HTTPStatus.FORBIDDEN
    assert b"/admin/gireve/" not in support.get(reverse("admin:index")).content


def test_admin_services_index_lists_both_services(data_client: Client) -> None:
    index = data_client.get(reverse("admin:index"))

    assert b"Gateway API (api-gateway)" in index.content
    assert b"Gireve OCPI (api-gireve)" in index.content


def test_register_app_models_skips_a_service_without_database() -> None:
    assert register_app_models("gireve", database_configured=False) == []
    assert CPOToken in admin.site._registry
