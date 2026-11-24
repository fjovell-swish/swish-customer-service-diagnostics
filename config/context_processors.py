from typing import Any

from django.conf import settings
from django.http import HttpRequest

from config import microsoft
from config.roles import DATA
from config.roles import SUPPORT
from config.roles import has_role
from config.tenancy import get_current_tenant


def navigation(request: HttpRequest) -> dict[str, Any]:
    """What the header offers: the tenant switcher and links, by role."""
    return {
        "can_query_data": has_role(request.user, DATA),
        "can_handle_cases": has_role(request.user, SUPPORT),
        "ocpp_tenants": settings.OCPP_TENANTS,
        "ocpp_current_tenant": get_current_tenant(),
        "microsoft_sign_in": microsoft.enabled(),
    }
