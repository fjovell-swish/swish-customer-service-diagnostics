from django.contrib import admin
from django.http import HttpRequest

from diagnostics.models import Case


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin[Case]):
    """The case history. Cases are created and answered on the workflow pages ("View on site")."""

    list_display = [
        "id",
        "identity",
        "tenant",
        "status",
        "likely_cause",
        "created_by",
        "created_at",
    ]
    list_filter = ["status", "tenant", "confidence"]
    search_fields = ["identity", "ticket", "likely_cause"]
    list_select_related = ["created_by"]
    date_hierarchy = "created_at"
    fields = [
        "identity",
        "tenant",
        "ticket",
        "status",
        "created_by",
        "created_at",
        "diagnosed_at",
        "likely_cause",
        "confidence",
        "customer_reply",
        "summary",
        "answers",
    ]
    readonly_fields = [
        "identity",
        "tenant",
        "created_by",
        "created_at",
        "diagnosed_at",
        "likely_cause",
        "confidence",
        "customer_reply",
        "summary",
        "answers",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
