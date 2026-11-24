from datetime import datetime

from django.conf import settings
from django.db import models
from django.urls import reverse

from diagnostics.assistant import Assessment
from diagnostics.jira import Issue
from diagnostics.workflow import Diagnosis


class Case(models.Model):
    """One "the charger doesn't work" case: the charger, the rep's answers, the diagnosis."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DIAGNOSED = "diagnosed", "Diagnosed"
        CLOSED = "closed", "Closed"

    identity = models.CharField("charger identity", max_length=255)
    tenant = models.CharField(max_length=63)
    ticket = models.CharField(
        max_length=255, blank=True, help_text="The support ticket's number or link."
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    answers = models.JSONField(default=dict, blank=True)
    # The diagnosis as written when the last question was answered, kept as it was: the charger's
    # live state moves on, the case records what support saw and told the customer.
    likely_cause = models.CharField(max_length=255, blank=True)
    confidence = models.CharField(max_length=16, blank=True)
    summary = models.TextField(blank=True)
    customer_reply = models.TextField(blank=True)
    diagnosed_at = models.DateTimeField(null=True, blank=True)
    # Claude's assessment (diagnostics/assistant.py), as returned, and the Jira escalation.
    assessment = models.JSONField(default=dict, blank=True)
    assessed_at = models.DateTimeField(null=True, blank=True)
    assessment_model = models.CharField(max_length=64, blank=True)
    jira_issue = models.CharField(
        max_length=255, blank=True, help_text="The Jira issue the case was escalated to."
    )
    jira_issue_url = models.URLField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"#{self.pk} {self.identity}"

    def get_absolute_url(self) -> str:
        return reverse("case", args=[self.pk])

    def record(self, diagnosis: Diagnosis, now: datetime) -> None:
        self.likely_cause = diagnosis.likely_cause
        self.confidence = diagnosis.confidence.label
        self.summary = diagnosis.summary
        self.customer_reply = diagnosis.customer_reply
        self.diagnosed_at = now
        self.status = self.Status.DIAGNOSED
        self.save()

    def record_assessment(self, assessment: Assessment, model: str, now: datetime) -> None:
        self.assessment = assessment.as_dict()
        self.assessment_model = model
        self.assessed_at = now
        self.save()

    def record_escalation(self, issue: Issue) -> None:
        self.jira_issue = issue.key
        self.jira_issue_url = issue.url
        self.save()
