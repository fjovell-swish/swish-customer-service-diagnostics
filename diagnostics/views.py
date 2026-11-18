from django.contrib import admin
from django.http import HttpRequest
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.utils import timezone

from diagnostics.checks import run_checks
from diagnostics.checks import verdict
from diagnostics.snapshot import collect
from diagnostics.snapshot import find_chargers


def diagnose(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    tenant = request.GET.get("tenant", "")
    context = admin.site.each_context(request) | {"title": "Charger diagnostics", "query": query}
    if not query:
        return TemplateResponse(request, "diagnostics/diagnose.html", context)

    matches = find_chargers(query)
    if tenant:
        matches = [match for match in matches if match.tenant == tenant]
    if len(matches) != 1:
        context["matches"] = matches
        return TemplateResponse(request, "diagnostics/diagnose.html", context)

    match = matches[0]
    now = timezone.now()
    snapshot = collect(match.tenant, match.charge_point, now)
    findings = run_checks(snapshot, now)
    severity, summary = verdict(findings)
    context |= {
        "snapshot": snapshot,
        "findings": findings,
        "verdict": severity,
        "summary": summary,
        "checked_at": now,
    }
    return TemplateResponse(request, "diagnostics/diagnose.html", context)
