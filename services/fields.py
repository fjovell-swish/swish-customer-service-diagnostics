from typing import Any

from django.db import models


class JSONField(models.JSONField):
    """JSONField that also reads Postgres `json` columns.

    Django expects `jsonb`, which its psycopg setup returns as text to decode. The services'
    SQLModel `JSON` columns are plain `json`, which psycopg already decodes into Python objects.
    """

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        if value is None or isinstance(value, str):
            return super().from_db_value(value, expression, connection)
        return value
