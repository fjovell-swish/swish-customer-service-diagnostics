from itertools import groupby

from django.contrib import admin
from django.http import HttpRequest
from django.http import HttpResponse
from django.template.response import TemplateResponse

from deployments.status import get_statuses


def deployment_status(request: HttpRequest) -> HttpResponse:
    statuses = get_statuses(refresh="refresh" in request.GET)
    services = [
        (service, list(rows))
        for service, rows in groupby(statuses, key=lambda status: status.service)
    ]
    context = admin.site.each_context(request) | {
        "title": "Deployment status",
        "services": services,
    }
    return TemplateResponse(request, "deployments/status.html", context)
