"""
The api-ocpp tenant the admin's pages read, per request (as in swish-admin).

The admin's generic pages can't say `.using()`: the chosen tenant is kept in the session and
exposed through a context variable that the database router reads, so every api-ocpp query of the
request hits that tenant's schema. The diagnostics code still picks its tenant explicitly.
"""

from collections.abc import Callable
from contextvars import ContextVar

from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse

SESSION_KEY = "ocpp_tenant"

current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)


def default_tenant() -> str:
    tenant: str = settings.OCPP_TENANTS[0]
    return tenant


def get_current_tenant() -> str:
    return current_tenant.get() or default_tenant()


class TenantMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = request.session.get(SESSION_KEY)
        if tenant not in settings.OCPP_TENANTS:
            tenant = default_tenant()
        token = current_tenant.set(tenant)
        try:
            return self.get_response(request)
        finally:
            current_tenant.reset(token)
