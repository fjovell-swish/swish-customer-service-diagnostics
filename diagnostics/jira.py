"""
Escalating a case to the tech team: a Jira issue (Jira Cloud's REST API v3, basic auth with an
API token) in JIRA_PROJECT, by default the IT project's incidents, where support escalates today.
"""

from dataclasses import dataclass

import httpx
from django.conf import settings

REQUEST_TIMEOUT_SECONDS = 10
# Jira refuses longer summaries.
MAX_TITLE_LENGTH = 255


@dataclass(frozen=True)
class Issue:
    key: str
    url: str


def enabled() -> bool:
    return bool(settings.JIRA_URL and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN)


def document(text: str) -> dict[str, object]:
    """Plain text as an Atlassian document: one paragraph per line, blank lines dropped."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in text.splitlines()
            if line.strip()
        ],
    }


class JiraClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url=settings.JIRA_URL,
            auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def create_issue(self, title: str, description: str) -> Issue:
        response = self.client.post(
            "/rest/api/3/issue",
            json={
                "fields": {
                    "project": {"key": settings.JIRA_PROJECT},
                    "issuetype": {"name": settings.JIRA_ISSUE_TYPE},
                    "summary": title[:MAX_TITLE_LENGTH],
                    "description": document(description),
                    "labels": settings.JIRA_LABELS,
                }
            },
        )
        response.raise_for_status()
        key: str = response.json()["key"]
        return Issue(key, f"{settings.JIRA_URL.rstrip('/')}/browse/{key}")
