from typing import Any

import pytest
from django.db import connection

from services.fields import JSONField


@pytest.fixture
def field() -> JSONField:
    return JSONField()


def test_json_field_passes_decoded_json_through(field: JSONField) -> None:
    # Postgres `json` columns: psycopg has already decoded them.
    assert field.from_db_value({"a": 1}, None, connection) == {"a": 1}


@pytest.mark.parametrize(("raw", "decoded"), [('{"a": 1}', {"a": 1}), (None, None)])
def test_json_field_decodes_text(field: JSONField, raw: str | None, decoded: Any) -> None:
    assert field.from_db_value(raw, None, connection) == decoded
