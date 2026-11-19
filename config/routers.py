from typing import Any

from django.db.models import Model

from config.tenancy import get_current_tenant

OCPP_APP_LABEL = "ocpp"

# Services with a single database, whose alias is their app label (settings.SERVICE_DATABASES).
SINGLE_DATABASE_APP_LABELS = {"gateway", "gireve"}


class ServiceRouter:
    """Keep the services' models off `default` and never migrate them.

    Without `.using()`, api-ocpp queries go to the tenant chosen in the admin's header
    (config/tenancy.py; the first tenant outside a request). Diagnostics always pass `.using()`.
    api-gateway's and api-gireve's go to their one database.
    """

    def db_for_read(self, model: type[Model], **hints: Any) -> str | None:
        app_label = model._meta.app_label
        if app_label == OCPP_APP_LABEL:
            return f"ocpp_{get_current_tenant()}"
        if app_label in SINGLE_DATABASE_APP_LABELS:
            return app_label
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
        # The services' schemas belong to the services (Alembic, create_all), never to this app.
        if app_label == OCPP_APP_LABEL or app_label in SINGLE_DATABASE_APP_LABELS:
            return False
        return db == "default"
