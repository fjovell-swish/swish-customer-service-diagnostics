from django.contrib import admin
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from mcp_api.models import PersonalToken

NAME_MAX_LENGTH = PersonalToken._meta.get_field("name").max_length


def tokens(request: HttpRequest) -> HttpResponse:
    """Your personal tokens for the MCP API: create one (shown once), or revoke one.

    **Template:** :template:`mcp_api/tokens.html`
    """
    user: User = request.user  # type: ignore[assignment]
    created = ""
    if request.method == "POST":
        if request.POST.get("action") == "revoke":
            user.personal_tokens.filter(pk=request.POST.get("token", "")).delete()
            return redirect("tokens")
        name = request.POST.get("name", "").strip()[:NAME_MAX_LENGTH] or "MCP client"
        _, created = PersonalToken.create(user, name, timezone.now())
    context = admin.site.each_context(request) | {
        "title": "Personal tokens for the MCP API",
        "tokens": user.personal_tokens.all(),
        "created": created,
        "mcp_url": request.build_absolute_uri("/mcp"),
    }
    return TemplateResponse(request, "mcp_api/tokens.html", context)
