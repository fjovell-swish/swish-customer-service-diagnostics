"""
Every model of a service app in the admin, read-only, with options derived from its fields
(adapted from swish-admin's services/admin_registration.py).

The models are generated, so list columns, filters and search fields are worked out here instead
of being written per model; per-model tweaks go in the `overrides` of the app's admin.py. Pages
read the tenant chosen in the admin's header (config/tenancy.py).
"""

from functools import cached_property
from typing import Any

from django.apps import apps
from django.contrib import admin
from django.core.paginator import Paginator
from django.db import connections
from django.db import models
from django.db.models import QuerySet
from django.forms import TextInput
from django.http import HttpRequest

from config.roles import DATA
from config.roles import has_role

# Below this estimated row count an exact COUNT(*) is cheap enough.
EXACT_COUNT_THRESHOLD = 100_000

MAX_LIST_DISPLAY = 8
MAX_LIST_FILTER = 6
MAX_SEARCH_FIELDS = 6

# Text columns worth searching on: charger identities, OCPI ids, RFID uids, emails, names.
SEARCHABLE_NAMES = {"identity", "uid", "name", "email", "id_token", "contract_id", "visual_number"}
SEARCHABLE_SUFFIXES = (
    "_identity",
    "_uid",
    "_name",
    "_email",
    "_number",
    "id_tag",
    "authorization_id",
)

TIMESTAMP_FIELDS = ("created_at", "updated_at")

# Columns people look for first in a list, shown right after the primary key when present.
KEY_COLUMNS = ("identity", "name", "uid", "evse_id", "email", "status", "connected", "is_active")


class EstimatedCountPaginator(Paginator[Any]):
    """Postgres' row estimate for unfiltered lists: COUNT(*) on meter values takes seconds."""

    @cached_property
    def count(self) -> int:
        # The admin's changelist always paginates a queryset.
        queryset: QuerySet[Any] = self.object_list  # type: ignore[assignment]
        connection = connections[queryset.db]
        if queryset.query.where or connection.vendor != "postgresql":
            return super().count
        with connection.cursor() as cursor:
            # to_regclass resolves through search_path, so this picks the current tenant's table.
            cursor.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s)",
                [queryset.model._meta.db_table],
            )
            row = cursor.fetchone()
        estimate = int(row[0]) if row else -1
        if estimate < EXACT_COUNT_THRESHOLD:
            return super().count
        return estimate


class ServiceModelAdmin(admin.ModelAdmin[Any]):
    """For the `data` role; read-only for everyone, superusers included: this app never writes
    to a service."""

    paginator = EstimatedCountPaginator
    show_full_result_count = False
    list_per_page = 50
    formfield_overrides = {
        # Most unbounded text columns are short ids; a one-line input reads better than a textarea.
        models.TextField: {"widget": TextInput(attrs={"size": 80})},
    }

    def has_module_permission(self, request: HttpRequest) -> bool:
        return has_role(request.user, DATA)

    def has_view_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        return has_role(request.user, DATA)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: models.Model | None = None) -> bool:
        return False


def concrete_fields(model: type[models.Model]) -> list[models.Field[Any, Any]]:
    return [
        field
        for field in model._meta.concrete_fields
        if not isinstance(field, models.CompositePrimaryKey)
    ]


def default_list_display(model: type[models.Model]) -> list[str]:
    pk_names = {field.name for field in model._meta.pk_fields}
    display = [field.name for field in concrete_fields(model) if field.name in pk_names]
    field_names = {field.name for field in concrete_fields(model)}
    timestamps = [name for name in TIMESTAMP_FIELDS if name in field_names]
    display += [name for name in KEY_COLUMNS if name in field_names and name not in display]
    for field in concrete_fields(model):
        if len(display) >= MAX_LIST_DISPLAY - len(timestamps):
            break
        if field.name in display or field.name in timestamps:
            continue
        if isinstance(field, models.JSONField):
            continue
        display.append(field.name)
    return display[: MAX_LIST_DISPLAY - len(timestamps)] + timestamps


def default_list_filter(model: type[models.Model]) -> list[str]:
    filters = [
        field.name
        for field in concrete_fields(model)
        if field.choices or isinstance(field, models.BooleanField)
    ][:MAX_LIST_FILTER]
    if any(field.name == "created_at" for field in concrete_fields(model)):
        filters.append("created_at")
    return filters


def default_search_fields(model: type[models.Model]) -> list[str]:
    fields = [
        field.name
        for field in concrete_fields(model)
        if isinstance(field, models.CharField | models.TextField)
        and not field.choices
        and (field.name in SEARCHABLE_NAMES or field.name.endswith(SEARCHABLE_SUFFIXES))
    ]
    return fields[:MAX_SEARCH_FIELDS]


def default_ordering(model: type[models.Model]) -> list[str]:
    if any(field.name == "created_at" for field in concrete_fields(model)):
        return ["-created_at"]
    return ["-pk"]


def default_options(model: type[models.Model]) -> dict[str, Any]:
    return {
        "list_display": default_list_display(model),
        "list_filter": default_list_filter(model),
        "search_fields": default_search_fields(model),
        "raw_id_fields": [
            field.name for field in concrete_fields(model) if isinstance(field, models.ForeignKey)
        ],
        "ordering": default_ordering(model),
    }


def register_app_models(
    app_label: str,
    overrides: dict[str, dict[str, Any]] | None = None,
    database_configured: bool = True,
) -> list[type[models.Model]]:
    """Register all models of `app_label`; `overrides` maps a model name to admin options.

    A service whose database isn't configured registers nothing: its pages could only fail.
    """
    if not database_configured:
        return []
    overrides = overrides or {}
    registered = []
    for model in apps.get_app_config(app_label).get_models():
        if isinstance(model._meta.pk, models.CompositePrimaryKey):
            # The admin refuses composite primary keys (still in Django 6.1). These are the
            # many-to-many link tables (e.g. charge_point_tariff_link); query them from the shell.
            continue
        options = default_options(model) | overrides.get(model.__name__, {})
        admin_class = type(f"{model.__name__}Admin", (ServiceModelAdmin,), options)
        admin.site.register(model, admin_class)
        registered.append(model)
    return registered
