import json
from http import HTTPStatus
from typing import Any

import httpx
import pytest
import respx

from diagnostics.jira import MAX_TITLE_LENGTH
from diagnostics.jira import Issue
from diagnostics.jira import JiraClient
from diagnostics.jira import document
from diagnostics.jira import enabled


@pytest.fixture
def jira_settings(settings: Any) -> Any:
    settings.JIRA_URL = "https://jira.test/"
    settings.JIRA_EMAIL = "support@example.com"
    settings.JIRA_API_TOKEN = "token"
    settings.JIRA_PROJECT = "ROT"
    settings.JIRA_ISSUE_TYPE = "[System] Incident"
    settings.JIRA_LABELS = ["jira_escalated"]
    return settings


def test_enabled_needs_the_credentials(jira_settings: Any) -> None:
    assert enabled() is True

    jira_settings.JIRA_API_TOKEN = ""
    assert enabled() is False


def test_document_one_paragraph_per_line() -> None:
    assert document("First\n\nSecond") == {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "First"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second"}]},
        ],
    }


@respx.mock
def test_create_issue(jira_settings: Any) -> None:
    route = respx.post("https://jira.test/rest/api/3/issue").respond(
        HTTPStatus.CREATED, json={"id": "1", "key": "ROT-1400"}
    )

    issue = JiraClient().create_issue("x" * (MAX_TITLE_LENGTH + 10), "What happens")

    assert issue == Issue("ROT-1400", "https://jira.test/browse/ROT-1400")
    fields = json.loads(route.calls.last.request.content)["fields"]
    assert fields["project"] == {"key": "ROT"}
    assert fields["issuetype"] == {"name": "[System] Incident"}
    assert fields["labels"] == ["jira_escalated"]
    assert len(fields["summary"]) == MAX_TITLE_LENGTH
    assert fields["description"] == document("What happens")
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")


@respx.mock
def test_create_issue_raises_when_jira_refuses(jira_settings: Any) -> None:
    respx.post("https://jira.test/rest/api/3/issue").respond(HTTPStatus.BAD_REQUEST)

    with pytest.raises(httpx.HTTPStatusError):
        JiraClient().create_issue("Title", "Description")
