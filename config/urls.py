from django.contrib import admin
from django.contrib.admindocs import urls as admindocs_urls
from django.urls import URLPattern
from django.urls import include
from django.urls import path

from config.roles import DATA
from config.roles import any_role_required
from config.roles import role_required
from config.views import healthz
from config.views import switch_tenant
from deployments.views import deployment_status
from diagnostics.views import case_detail
from diagnostics.views import guide
from diagnostics.views import start
from mcp_api.views import tokens

admin.site.site_header = "Swish charger diagnostics"
admin.site.site_title = "Swish charger diagnostics"
admin.site.index_title = "Cases and the services' data (read-only)"

# admindocs only asks for staff; a staff user with neither role (made by hand) gets nothing here.
admindocs_patterns = [
    URLPattern(
        pattern.pattern, any_role_required(pattern.callback), pattern.default_args, pattern.name
    )
    for pattern in admindocs_urls.urlpatterns
    if isinstance(pattern, URLPattern)
]

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", admin.site.admin_view(start), name="start"),
    path("cases/<int:pk>/", admin.site.admin_view(case_detail), name="case"),
    path("guide/", admin.site.admin_view(guide), name="guide"),
    path("tokens/", admin.site.admin_view(any_role_required(tokens)), name="tokens"),
    path("admin/tenant/", switch_tenant, name="switch-tenant"),
    path(
        "admin/deployments/",
        admin.site.admin_view(role_required(DATA)(deployment_status)),
        name="deployment-status",
    ),
    # Before admin/, which would otherwise take these URLs.
    path("admin/doc/", include(admindocs_patterns)),
    path("admin/", admin.site.urls),
]
