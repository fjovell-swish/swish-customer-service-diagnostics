from typing import Any

from django.db.models import Model

from config.tenancy import get_current_tenant

OCPP_APP_LABEL = "ocpp"


class ServiceRouter:
    """Keep api-ocpp models off `default` and never migrate them.

    Without `.using()`, api-ocpp queries go to the tenant chosen in the admin's header
    (config/tenancy.py; the first tenant outside a request). Diagnostics always pass `.using()`.
    """

    def db_for_read(self, model: type[Model], **hints: Any) -> str | None:
        if model._meta.app_label == OCPP_APP_LABEL:
            return f"ocpp_{get_current_tenant()}"
        return None

    def db_for_write(self, model: type[Model], **hints: Any) -> str | None:
        return self.db_for_read(model, **hints)

    def allow_relation(self, obj1: Model, obj2: Model, **hints: Any) -> bool | None:
        # Every tenant alias holds the same api-ocpp schema: an object read from one tenant
        # relates to the others of that tenant, whichever alias the default would pick.
        if obj1._meta.app_label == obj2._meta.app_label == OCPP_APP_LABEL:
            return True
        return None

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool:
        # api-ocpp's schemas belong to api-ocpp (Alembic), never to this app.
        if app_label == OCPP_APP_LABEL:
            return False
        return db == "default"
