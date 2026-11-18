from django.contrib import admin
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.urls import path

from diagnostics.views import diagnose

admin.site.site_header = "Swish charger diagnostics"
admin.site.site_title = "Swish charger diagnostics"
admin.site.index_title = "Support users"


def healthcheck(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthcheck", healthcheck, name="healthcheck"),
    path("", admin.site.admin_view(diagnose), name="diagnose"),
    path("admin/", admin.site.urls),
]
