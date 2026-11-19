from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from config.roles import DATA
from config.roles import role_required
from config.tenancy import SESSION_KEY


def healthz(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"status": "ok"})


@require_POST
@staff_member_required
@role_required(DATA)
def switch_tenant(request: HttpRequest) -> HttpResponse:
    tenant = request.POST.get("tenant")
    if tenant in settings.OCPP_TENANTS:
        request.session[SESSION_KEY] = tenant
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("admin:index")
    # Ids differ between tenants, so an object page from the previous tenant would 404.
    ocpp_index = reverse("admin:app_list", args=["ocpp"])
    if next_url.startswith(ocpp_index):
        next_url = ocpp_index
    return HttpResponseRedirect(next_url)
