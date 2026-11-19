from collections.abc import Callable
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connection

from services.ocpp.management.commands.regenerate_ocpp_models import JSON_TYPE_OID
from services.ocpp.management.commands.regenerate_ocpp_models import Command


@pytest.fixture
def sample_tables(db: None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE charge_points_v16 (id char(32) PRIMARY KEY, identity varchar NOT NULL"
            " UNIQUE)"
        )
        cursor.execute(
            "CREATE TABLE connectors_v16 (id char(32) PRIMARY KEY,"
            " charge_point_id char(32) REFERENCES charge_points_v16 (id))"
        )
        cursor.execute("CREATE TABLE brand_new_things (id integer PRIMARY KEY)")
        cursor.execute("CREATE TABLE spatial_ref_sys (srid integer PRIMARY KEY)")


@pytest.fixture
def regenerate(tmp_path: Path) -> Callable[[], str]:
    def run() -> str:
        output = tmp_path / "models.py"
        call_command(
            "regenerate_ocpp_models", database="default", output=output, stdout=StringIO()
        )
        return output.read_text()

    return run


@pytest.fixture
def command() -> Command:
    command = Command()
    command.enum_type_oids = None
    return command


@pytest.fixture
def make_row() -> Callable[..., Any]:
    def factory(type_code: Any) -> Any:
        return SimpleNamespace(
            type_code=type_code, display_size=None, collation=None, precision=None, scale=None
        )

    return factory


def test_regenerate_keeps_class_names_the_code_imports(
    sample_tables: None, regenerate: Callable[[], str]
) -> None:
    models = regenerate()

    assert "class ChargePointV16(models.Model):" in models
    assert "class ConnectorV16(models.Model):" in models
    assert "charge_point = models.ForeignKey(ChargePointV16, models.DO_NOTHING" in models


def test_regenerate_names_unknown_tables_like_inspectdb(
    sample_tables: None, regenerate: Callable[[], str]
) -> None:
    assert "class BrandNewThings(models.Model):" in regenerate()


def test_regenerate_skips_tables_that_are_not_api_ocpps(
    sample_tables: None, regenerate: Callable[[], str]
) -> None:
    assert "spatial_ref_sys" not in regenerate()


def test_regenerate_writes_header_instead_of_inspectdb_instructions(
    sample_tables: None, regenerate: Callable[[], str]
) -> None:
    models = regenerate()

    assert models.startswith('"""Unmanaged models for the api-ocpp database.')
    assert "from services import fields" in models
    assert "auto-generated Django model module" not in models
    assert "managed = False" in models


def test_regenerate_output_is_importable_python(
    sample_tables: None, regenerate: Callable[[], str]
) -> None:
    compile(regenerate(), "models.py", "exec")


def test_get_field_type_reads_postgres_json_as_json(
    command: Command, make_row: Callable[..., Any]
) -> None:
    assert command.get_field_type(connection, "jobs", make_row(JSON_TYPE_OID)) == (
        "fields.JSONField",
        {},
        [],
    )


def test_get_field_type_types_postgres_enums_as_text(
    command: Command, make_row: Callable[..., Any]
) -> None:
    enum_oid = 90001
    command.enum_type_oids = {enum_oid}
    postgres = SimpleNamespace(vendor="postgresql")

    assert command.get_field_type(postgres, "jobs", make_row(enum_oid)) == ("TextField", {}, [])


def test_enum_types_empty_outside_postgres(command: Command) -> None:
    assert command.enum_types(SimpleNamespace(vendor="sqlite")) == set()


@pytest.mark.postgres
@pytest.mark.django_db(databases="__all__")
def test_regenerate_against_postgres_api_ocpp_tables(ocpp_tables: None, tmp_path: Path) -> None:
    """The real path: introspect a tenant's api-ocpp tables, enum lookup in pg_type included."""
    output = tmp_path / "models.py"

    call_command(
        "regenerate_ocpp_models", database="ocpp_eosgie", output=output, stdout=StringIO()
    )

    models = output.read_text()
    assert "class ChargePointV16(models.Model):" in models
    assert "class TransactionV16(models.Model):" in models
