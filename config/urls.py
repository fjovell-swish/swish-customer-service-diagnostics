from django.contrib import admin
from django.urls import path

from config.roles import DATA
from config.roles import role_required
from config.views import healthz
from config.views import switch_tenant
from deployments.views import deployment_status
from diagnostics.views import case_detail
from diagnostics.views import start

admin.site.site_header = "Swish charger diagnostics"
admin.site.site_title = "Swish charger diagnostics"
admin.site.index_title = "Cases and the services' data (read-only)"


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", admin.site.admin_view(start), name="start"),
    path("cases/<int:pk>/", admin.site.admin_view(case_detail), name="case"),
    path("admin/tenant/", switch_tenant, name="switch-tenant"),
    path(
        "admin/deployments/",
        admin.site.admin_view(role_required(DATA)(deployment_status)),
        name="deployment-status",
    ),
    path("admin/", admin.site.urls),
]
