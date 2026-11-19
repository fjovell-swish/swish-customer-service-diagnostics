from django.contrib import admin
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.urls import path

from diagnostics.views import case_detail
from diagnostics.views import start

admin.site.site_header = "Swish charger diagnostics"
admin.site.site_title = "Swish charger diagnostics"
admin.site.index_title = "Cases and support users"


def healthz(request: HttpRequest) -> HttpResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", admin.site.admin_view(start), name="start"),
    path("cases/<int:pk>/", admin.site.admin_view(case_detail), name="case"),
    path("admin/", admin.site.urls),
]
