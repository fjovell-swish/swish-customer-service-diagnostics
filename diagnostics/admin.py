from django.contrib import admin
from django.http import HttpRequest

from config.roles import SUPPORT
from config.roles import has_role
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
        "jira_issue",
        "created_by",
        "created_at",
    ]
    list_filter = ["status", "tenant", "confidence"]
    search_fields = ["identity", "ticket", "jira_issue", "likely_cause"]
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
        "jira_issue",
        "jira_issue_url",
        "assessed_at",
        "assessment_model",
        "assessment",
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
        "assessed_at",
        "assessment_model",
        "assessment",
    ]

    # The `support` role sees the history and can update a case's status and ticket; deleting
    # stays with superusers (Django's model permissions).
    def has_module_permission(self, request: HttpRequest) -> bool:
        return has_role(request.user, SUPPORT)

    def has_view_permission(self, request: HttpRequest, obj: Case | None = None) -> bool:
        return has_role(request.user, SUPPORT)

    def has_change_permission(self, request: HttpRequest, obj: Case | None = None) -> bool:
        return has_role(request.user, SUPPORT)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
