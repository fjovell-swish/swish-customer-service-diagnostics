"""api-ocpp's tables in the admin: every one listed, read-only, per tenant."""

from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.db import connections
from django.db.models import Model
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse

from config.roles import DATA
from config.roles import SUPPORT
from config.routers import ServiceRouter
from config.tenancy import SESSION_KEY
from config.tenancy import current_tenant
from diagnostics.admin import CaseAdmin
from diagnostics.models import Case
from services import admin_registration
from services.admin_registration import EstimatedCountPaginator
from services.admin_registration import ServiceModelAdmin
from services.admin_registration import default_list_display
from services.admin_registration import default_list_filter
from services.admin_registration import default_ordering
from services.admin_registration import default_search_fields
from services.ocpp.models import ChargePointTariffLink
from services.ocpp.models import ChargePointV16
from services.ocpp.models import Incident
from services.ocpp.models import Job

pytestmark = [pytest.mark.django_db(databases="__all__"), pytest.mark.usefixtures("ocpp_tables")]

OCPP_MODELS = [model for model in admin.site._registry if model._meta.app_label == "ocpp"]


@pytest.fixture
def staff_client(make_client: Callable[..., Client]) -> Client:
    """Someone with the data role, as Microsoft's sign-in creates them: no model permissions."""
    return make_client(DATA)


@pytest.fixture
def charger(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    tenants: list[str],
) -> Model:
    return save(tenants[0], make_charge_point())


@pytest.fixture
def other_tenant_charger(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    tenants: list[str],
) -> Model:
    return save(tenants[1], make_charge_point(identity="OTHER-TENANT-1"))


@pytest.fixture
def changelist() -> str:
    return reverse("admin:ocpp_chargepointv16_changelist")


def test_admin_ocpp_registers_every_table_but_the_link_tables() -> None:
    assert len(OCPP_MODELS) == 35
    assert ChargePointTariffLink not in admin.site._registry


@pytest.mark.parametrize("model", OCPP_MODELS, ids=lambda model: model.__name__)
def test_admin_ocpp_every_table_lists_for_the_data_role(
    staff_client: Client, model: type[Model]
) -> None:
    url = reverse(f"admin:ocpp_{model._meta.model_name}_changelist")

    assert staff_client.get(url).status_code == HTTPStatus.OK


def test_admin_ocpp_index_lists_the_tables(staff_client: Client) -> None:
    response = staff_client.get(reverse("admin:index"))

    assert b"OCPP API (api-ocpp)" in response.content
    assert b'name="tenant"' in response.content  # the tenant switcher in the header


def test_admin_ocpp_search_by_identity(
    staff_client: Client, charger: ChargePointV16, changelist: str
) -> None:
    response = staff_client.get(changelist, {"q": "CP001"})

    assert list(response.context["cl"].result_list) == [charger]


def test_admin_ocpp_object_page_is_read_only(
    staff_client: Client, charger: ChargePointV16
) -> None:
    url = reverse("admin:ocpp_chargepointv16_change", args=[charger.pk])

    response = staff_client.get(url)

    assert response.status_code == HTTPStatus.OK
    assert b'name="_save"' not in response.content
    assert staff_client.post(url, {"identity": "changed"}).status_code == HTTPStatus.FORBIDDEN


def test_admin_ocpp_read_only_for_superusers_too(admin_client: Client, charger: Model) -> None:
    delete = reverse("admin:ocpp_chargepointv16_delete", args=[charger.pk])

    assert admin_client.get(reverse("admin:ocpp_chargepointv16_add")).status_code == 403
    assert admin_client.post(delete, {"post": "yes"}).status_code == HTTPStatus.FORBIDDEN
    assert ChargePointV16.objects.using("ocpp_public").filter(pk=charger.pk).exists()


def test_admin_ocpp_not_for_non_staff(rf: RequestFactory, db: None) -> None:
    request = rf.get("/")
    request.user = User.objects.create_user("customer")
    model_admin = ServiceModelAdmin(ChargePointV16, admin.site)

    assert not model_admin.has_module_permission(request)
    assert not model_admin.has_view_permission(request)


def test_admin_ocpp_switching_tenant(
    staff_client: Client,
    charger: ChargePointV16,
    other_tenant_charger: ChargePointV16,
    changelist: str,
    tenants: list[str],
) -> None:
    response = staff_client.post(
        reverse("switch-tenant"), {"tenant": tenants[1], "next": changelist}
    )

    # An object page id doesn't carry over to another tenant: back to the app's index.
    assert response["Location"] == reverse("admin:app_list", args=["ocpp"])
    assert list(staff_client.get(changelist).context["cl"].result_list) == [other_tenant_charger]


def test_admin_ocpp_switching_keeps_pages_outside_api_ocpp(
    staff_client: Client, tenants: list[str]
) -> None:
    cases = reverse("admin:diagnostics_case_changelist")

    response = staff_client.post(reverse("switch-tenant"), {"tenant": tenants[1], "next": cases})

    assert response["Location"] == cases


def test_admin_ocpp_switching_ignores_unknown_tenants_and_foreign_urls(
    staff_client: Client, charger: ChargePointV16, changelist: str
) -> None:
    response = staff_client.post(
        reverse("switch-tenant"), {"tenant": "nope", "next": "https://evil.example/"}
    )

    assert response["Location"] == reverse("admin:index")
    assert list(staff_client.get(changelist).context["cl"].result_list) == [charger]


def test_admin_ocpp_unknown_tenant_in_session_falls_back(
    staff_client: Client, charger: ChargePointV16, changelist: str
) -> None:
    session = staff_client.session
    session[SESSION_KEY] = "gone"
    session.save()

    assert list(staff_client.get(changelist).context["cl"].result_list) == [charger]


def test_router_reads_the_tenant_chosen_for_the_request(tenants: list[str]) -> None:
    token = current_tenant.set(tenants[1])
    try:
        assert ServiceRouter().db_for_read(ChargePointV16) == f"ocpp_{tenants[1]}"
    finally:
        current_tenant.reset(token)


def test_default_list_display_puts_keys_first_and_timestamps_last() -> None:
    display = default_list_display(ChargePointV16)

    assert display[:3] == ["id", "identity", "status"]
    assert display[-2:] == ["created_at", "updated_at"]
    assert len(display) == admin_registration.MAX_LIST_DISPLAY


def test_default_list_display_skips_json_columns() -> None:
    assert "request" not in default_list_display(Job)


def test_default_list_filter_booleans_and_creation_date() -> None:
    filters = default_list_filter(ChargePointV16)

    assert "connected" in filters and filters[-1] == "created_at"


def test_default_search_fields() -> None:
    fields = default_search_fields(ChargePointV16)

    assert {"identity", "serial_number", "customer_name"} <= set(fields)
    assert len(fields) <= admin_registration.MAX_SEARCH_FIELDS


def test_default_ordering() -> None:
    assert default_ordering(ChargePointV16) == ["-created_at"]
    assert default_ordering(Incident) == ["-pk"]


def test_paginator_counts_exactly_on_small_tables(charger: ChargePointV16) -> None:
    paginator = EstimatedCountPaginator(ChargePointV16.objects.using("ocpp_public").all(), 10)

    assert paginator.count == 1


@pytest.mark.postgres
def test_paginator_uses_postgres_estimate_on_big_tables(
    charger: ChargePointV16, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connections["ocpp_public"].cursor() as cursor:
        cursor.execute("ANALYZE charge_points_v16")
        cursor.execute(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = 'charge_points_v16'"
        )
        estimate = cursor.fetchone()[0]
    monkeypatch.setattr(admin_registration, "EXACT_COUNT_THRESHOLD", -1)

    paginator = EstimatedCountPaginator(ChargePointV16.objects.using("ocpp_public").all(), 10)

    assert paginator.count == estimate


@pytest.mark.postgres
def test_paginator_exact_when_postgres_has_no_estimate(charger: ChargePointV16) -> None:
    # A table never analysed has no estimate (-1): count it.
    paginator = EstimatedCountPaginator(ChargePointV16.objects.using("ocpp_public").all(), 10)

    assert paginator.count == 1


def test_case_admin_for_the_support_role(
    make_client: Callable[..., Client], tenants: list[str], rf: RequestFactory
) -> None:
    case = Case.objects.create(identity="X", tenant=tenants[0])
    client = make_client(SUPPORT)
    request = rf.get("/")
    request.user = User.objects.get(username="ana@swish.example")
    case_admin: Any = CaseAdmin(Case, admin.site)

    assert client.get(reverse("admin:diagnostics_case_changelist")).status_code == 200
    assert case_admin.has_change_permission(request, case)
    assert not case_admin.has_delete_permission(request, case)
