"""
PostgreSQL through PgBouncer in transaction pooling (Azure's built-in PgBouncer, port 6432).

There, consecutive statements of one client can run on different server connections, so settings
made when connecting (the tenant's `search_path`, `default_transaction_read_only`) only follow
the client if PgBouncer tracks them, which depends on its version and configuration. A query for
one api-ocpp tenant could then read another tenant's schema. This backend doesn't rely on it:
every statement runs in a transaction that first sets them with SET LOCAL, so they hold for that
statement whatever server connection it gets.

The settings to pin come from the alias's PIN (config/settings/base.py, `pgbouncer=True`):
``{"search_path": "<schema>" or None, "read_only": bool}``. Server-side cursors are off for
these aliases (DISABLE_SERVER_SIDE_CURSORS), and Django's psycopg backend doesn't use prepared
statements by default: the two other things transaction pooling breaks.
"""

from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.backends.postgresql import base
from psycopg import sql

PIN = "PIN"


def pin_statement(pin: dict[str, Any]) -> sql.Composed | None:
    """The SET LOCAL statements for a PIN; None when it pins nothing."""
    statements: list[sql.Composable] = []
    if pin.get("search_path"):
        statements.append(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(pin["search_path"]))
        )
    if pin.get("read_only"):
        statements.append(sql.SQL("SET LOCAL transaction_read_only TO on"))
    return sql.SQL("; ").join(statements) if statements else None


class DatabaseWrapper(base.DatabaseWrapper):
    def __init__(self, settings_dict: dict[str, Any], alias: str = "default") -> None:
        super().__init__(settings_dict, alias)
        self.pin_statement = pin_statement(settings_dict.get(PIN) or {})
        if self.pin_statement is not None:
            self.execute_wrappers.append(self.pinned)

    def pinned(
        self,
        execute: Callable[..., Any],
        statement: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        # Inside an atomic block the statement already shares its transaction; otherwise this
        # opens one around the two. No savepoint: it would be a statement, and pinned in turn.
        with transaction.atomic(using=self.alias, savepoint=False):
            # The DB-API cursor, not Django's: Django's would run this wrapper again.
            context["cursor"].cursor.execute(self.pin_statement)
            return execute(statement, params, many, context)
