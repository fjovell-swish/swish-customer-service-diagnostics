"""The services' connections through PgBouncer: settings pinned per transaction."""

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import DatabaseError
from django.db import connections
from django.db import transaction

from config.pgbouncer.base import DatabaseWrapper
from config.pgbouncer.base import pin_statement
from config.settings.base import PGBOUNCER_ENGINE
from config.settings.base import ocpp_databases
from config.settings.base import service_database

URL = "postgres://reader:secret@pgbouncer.example:6432/ocpp"


@pytest.fixture
def make_pinned() -> Iterator[Any]:
    """A connection to the test Postgres through this backend, with the given PIN."""
    opened: list[DatabaseWrapper] = []

    def factory(**pin: Any) -> DatabaseWrapper:
        settings_dict = connections["default"].settings_dict | {"PIN": pin}
        connection = DatabaseWrapper(settings_dict, alias="pinned")
        # transaction.atomic() finds the connection by its alias.
        connections["pinned"] = connection
        opened.append(connection)
        return connection

    yield factory
    for connection in opened:
        connection.close()
    del connections["pinned"]


def show(connection: DatabaseWrapper, setting: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {setting}")
        value: str = cursor.fetchone()[0]
    return value


def test_settings_ocpp_tenants_through_pgbouncer() -> None:
    databases = ocpp_databases(URL, ["public", "eosgie"], read_only=True, pgbouncer=True)

    eosgie = databases["ocpp_eosgie"]
    assert eosgie["ENGINE"] == PGBOUNCER_ENGINE
    assert eosgie["DISABLE_SERVER_SIDE_CURSORS"] is True
    assert eosgie["PIN"] == {"search_path": "eosgie", "read_only": True}
    # Nothing set at connect time: PgBouncer may not keep it.
    assert "options" not in eosgie.get("OPTIONS", {})
    assert databases["ocpp_public"]["PIN"]["search_path"] == "public"


def test_settings_service_through_pgbouncer() -> None:
    config = service_database(URL, read_only=True, pgbouncer=True)

    assert config["ENGINE"] == PGBOUNCER_ENGINE
    assert config["PIN"] == {"search_path": None, "read_only": True}
    assert "options" not in config.get("OPTIONS", {})


def test_settings_without_pgbouncer_keep_the_connect_options() -> None:
    tenant = ocpp_databases(URL, ["eosgie"], read_only=True)["ocpp_eosgie"]
    service = service_database(URL, read_only=True)

    assert tenant["ENGINE"] == service["ENGINE"] == "django.db.backends.postgresql"
    assert "PIN" not in tenant and "PIN" not in service
    assert "search_path=eosgie" in tenant["OPTIONS"]["options"]
    assert service["OPTIONS"]["options"] == "-c default_transaction_read_only=on"


def test_pin_statement_sets_what_is_pinned() -> None:
    both = pin_statement({"search_path": "eosgie", "read_only": True})
    read_only = pin_statement({"search_path": None, "read_only": True})

    assert both is not None and read_only is not None
    assert both.as_string(None) == (
        'SET LOCAL search_path TO "eosgie"; SET LOCAL transaction_read_only TO on'
    )
    assert read_only.as_string(None) == "SET LOCAL transaction_read_only TO on"


def test_pin_statement_nothing_to_pin() -> None:
    assert pin_statement({}) is None
    assert pin_statement({"search_path": None, "read_only": False}) is None


@pytest.mark.postgres
@pytest.mark.django_db
def test_pinned_every_statement_gets_the_settings(make_pinned: Any) -> None:
    connection = make_pinned(search_path="eosgie", read_only=True)

    assert show(connection, "search_path") == "eosgie"
    assert show(connection, "transaction_read_only") == "on"


@pytest.mark.postgres
@pytest.mark.django_db
def test_pinned_settings_last_one_transaction(make_pinned: Any) -> None:
    """SET LOCAL: nothing stays on the server connection for the next client to inherit."""
    connection = make_pinned(search_path="eosgie", read_only=True)
    show(connection, "search_path")

    # Straight on the psycopg connection, so not pinned.
    raw = connection.connection.execute("SHOW search_path").fetchone()

    assert raw is not None and raw[0] != "eosgie"


@pytest.mark.postgres
@pytest.mark.django_db
def test_pinned_read_only_refuses_writes(make_pinned: Any) -> None:
    connection = make_pinned(search_path=None, read_only=True)

    with pytest.raises(DatabaseError, match="read-only transaction"):
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE pinned_write (id integer)")


@pytest.mark.postgres
@pytest.mark.django_db
def test_pinned_inside_an_atomic_block(make_pinned: Any) -> None:
    connection = make_pinned(search_path="eosgie", read_only=True)

    with transaction.atomic(using=connection.alias):
        first = show(connection, "search_path")
        second = show(connection, "transaction_read_only")

    assert (first, second) == ("eosgie", "on")


@pytest.mark.postgres
@pytest.mark.django_db
def test_pinned_nothing_to_pin_runs_as_is(make_pinned: Any) -> None:
    connection = make_pinned()

    assert connection.execute_wrappers == []
    assert show(connection, "transaction_read_only") == "off"
