"""The workflow's pages and the Case model, on api-ocpp's tables in the tenants' test databases."""

from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.db.models import Model
from django.test import Client
from django.urls import reverse

from diagnostics import assistant
from diagnostics.admin import CaseAdmin
from diagnostics.assistant import Assessment
from diagnostics.jira import Issue
from diagnostics.jira import JiraClient
from diagnostics.models import Case
from diagnostics.workflow import Confidence
from diagnostics.workflow import Diagnosis
from diagnostics.workflow import Situation
from services.ocpp.models import ChargePointV16

pytestmark = [pytest.mark.django_db(databases="__all__"), pytest.mark.usefixtures("ocpp_tables")]


@pytest.fixture
def support_user(admin_client: Client) -> User:
    return User.objects.get(username="support")


@pytest.fixture
def offline_charger(
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    make_connector: Callable[..., Model],
    tenants: list[str],
) -> ChargePointV16:
    charge_point = save(tenants[1], make_charge_point(identity="EOS-1", connected=False))
    save(tenants[1], make_connector(charge_point=charge_point))
    return charge_point  # type: ignore[return-value]


@pytest.fixture
def case(offline_charger: ChargePointV16, tenants: list[str], support_user: User) -> Case:
    return Case.objects.create(identity="EOS-1", tenant=tenants[1], created_by=support_user)


@pytest.fixture
def case_url(case: Case) -> str:
    return reverse("case", args=[case.pk])


@pytest.fixture
def answer(admin_client: Client, case_url: str) -> Callable[..., Any]:
    def post(value: str, action: str = "answer") -> Any:
        return admin_client.post(case_url, {"action": action, "answer": value})

    return post


def test_start_requires_login(client: Client, db: None) -> None:
    response = client.get(reverse("start"))

    assert response.status_code == HTTPStatus.FOUND
    assert "/admin/login/" in response["Location"]


def test_start_page_lists_latest_cases(admin_client: Client, case: Case) -> None:
    response = admin_client.get(reverse("start"))

    assert response.status_code == HTTPStatus.OK
    assert list(response.context["recent_cases"]) == [case]
    assert response.context["matches"] == []


def test_start_search_offers_to_start_a_case(
    admin_client: Client, offline_charger: ChargePointV16, tenants: list[str]
) -> None:
    response = admin_client.get(reverse("start"), {"q": "eos"})

    assert [m.charge_point.identity for m in response.context["matches"]] == ["EOS-1"]
    assert b'name="ticket"' in response.content


def test_start_search_without_match(admin_client: Client) -> None:
    response = admin_client.get(reverse("start"), {"q": "nothing-like-it"})

    assert b"No charger matches" in response.content


def test_start_creates_the_case(
    admin_client: Client, offline_charger: ChargePointV16, tenants: list[str], support_user: User
) -> None:
    response = admin_client.post(
        reverse("start"), {"identity": "EOS-1", "tenant": tenants[1], "ticket": "ZD-123"}
    )

    case = Case.objects.get()
    assert response["Location"] == case.get_absolute_url()
    assert (case.ticket, case.created_by, case.status) == ("ZD-123", support_user, "open")


def test_start_refuses_an_unknown_tenant(admin_client: Client) -> None:
    response = admin_client.post(reverse("start"), {"identity": "X", "tenant": "nope"})

    assert response["Location"] == reverse("start")
    assert not Case.objects.exists()


def test_case_asks_the_first_question(admin_client: Client, case_url: str) -> None:
    response = admin_client.get(case_url)

    assert response.context["question"].key == "when"
    assert b"Charger offline" in response.content  # the live findings, beside the question


def test_case_workflow_ends_in_a_diagnosis(
    admin_client: Client, case: Case, case_url: str, answer: Callable[..., Any]
) -> None:
    for value in ["now", "dead", "no"]:  # when, symptom, power (the charger is offline)
        assert answer(value).status_code == HTTPStatus.FOUND

    response = admin_client.get(case_url)

    case.refresh_from_db()
    assert case.answers == {"when": "now", "symptom": "dead", "power": "no"}
    assert (case.status, case.likely_cause, case.confidence) == (
        "diagnosed",
        "No power at the charger",
        "high",
    )
    assert case.summary.startswith("Charger: EOS-1")
    assert response.context["question"] is None
    assert b"Reply to the customer" in response.content


def test_case_free_text_answer(
    admin_client: Client, case: Case, case_url: str, answer: Callable[..., Any]
) -> None:
    for value in ["now", "refused", "yes", "badge"]:  # when, symptom, power, start
        answer(value)
    assert admin_client.get(case_url).context["question"].key == "badge"

    answer(" b42 ")

    case.refresh_from_db()
    assert case.answers["badge"] == "b42"  # Django strips free text


def test_case_rejects_an_answer_that_is_not_a_choice(
    case: Case, answer: Callable[..., Any]
) -> None:
    response = answer("tomorrow")

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors
    case.refresh_from_db()
    assert case.answers == {}


def test_case_back_drops_the_last_answer(case: Case, answer: Callable[..., Any]) -> None:
    answer("now")
    answer("dead")

    answer("", action="back")

    case.refresh_from_db()
    assert case.answers == {"when": "now"}


def test_case_restart_clears_the_answers(case: Case, answer: Callable[..., Any]) -> None:
    answer("now")

    answer("", action="restart")

    case.refresh_from_db()
    assert case.answers == {}


def test_case_close_keeps_the_diagnosis(
    admin_client: Client, case: Case, case_url: str, answer: Callable[..., Any]
) -> None:
    for value in ["now", "dead", "no"]:
        answer(value)
    admin_client.get(case_url)

    answer("", action="close")
    response = admin_client.get(case_url)

    case.refresh_from_db()
    assert (case.status, case.likely_cause) == ("closed", "No power at the charger")
    assert response.context["question"] is None


def test_case_rediagnose_reopens_and_writes_it_again(
    admin_client: Client, case: Case, case_url: str, answer: Callable[..., Any]
) -> None:
    for value in ["now", "dead", "no"]:
        answer(value)
    admin_client.get(case_url)
    first = case.__class__.objects.get().diagnosed_at

    answer("", action="rediagnose")
    admin_client.get(case_url)

    case.refresh_from_db()
    assert case.status == "diagnosed" and case.diagnosed_at != first


def test_case_unknown_action_changes_nothing(case: Case, answer: Callable[..., Any]) -> None:
    response = answer("", action="dance")

    case.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND and case.answers == {}


def test_case_for_a_charger_that_disappeared(
    admin_client: Client, tenants: list[str], support_user: User
) -> None:
    gone = Case.objects.create(identity="GONE", tenant=tenants[0], created_by=support_user)

    assert admin_client.get(gone.get_absolute_url()).status_code == HTTPStatus.NOT_FOUND


def test_case_str_and_url(case: Case) -> None:
    assert str(case) == f"#{case.pk} EOS-1"
    assert case.get_absolute_url() == f"/cases/{case.pk}/"


def test_case_record(case: Case, now: datetime) -> None:
    diagnosis = Diagnosis("Cause", Confidence.MEDIUM, "because", ["act"], "reply", "summary")

    case.record(diagnosis, now)

    case.refresh_from_db()
    assert (case.likely_cause, case.confidence, case.summary, case.customer_reply) == (
        "Cause",
        "medium",
        "summary",
        "reply",
    )
    assert case.diagnosed_at == now


def test_admin_case_pages(admin_client: Client, case: Case) -> None:
    changelist = admin_client.get(reverse("admin:diagnostics_case_changelist"))
    change = admin_client.get(reverse("admin:diagnostics_case_change", args=[case.pk]))

    assert changelist.status_code == change.status_code == HTTPStatus.OK
    assert b"EOS-1" in changelist.content


def test_admin_cases_are_not_added_by_hand(rf: Any) -> None:
    case_admin = CaseAdmin(Case, admin_site=admin.site)

    assert case_admin.has_add_permission(rf.get("/")) is False


# --- Claude's assessment and the Jira escalation ---


@pytest.fixture
def diagnosed(admin_client: Client, case: Case, case_url: str, answer: Callable[..., Any]) -> Case:
    for value in ["now", "dead", "no"]:
        answer(value)
    admin_client.get(case_url)
    case.refresh_from_db()
    return case


@pytest.fixture
def claude_on(settings: Any) -> Any:
    settings.ANTHROPIC_API_KEY = "sk-test"
    settings.ANTHROPIC_MODEL = "claude-sonnet-5-5"
    return settings


@pytest.fixture
def jira_on(settings: Any) -> Any:
    settings.JIRA_URL = "https://jira.test"
    settings.JIRA_EMAIL = "support@example.com"
    settings.JIRA_API_TOKEN = "token"
    return settings


@pytest.fixture
def assessed(diagnosed: Case, make_assessment: Callable[..., Assessment], now: datetime) -> Case:
    diagnosed.record_assessment(make_assessment(), "claude-sonnet-5-5", now)
    return diagnosed


@pytest.fixture
def fake_assess(
    monkeypatch: pytest.MonkeyPatch, make_assessment: Callable[..., Assessment]
) -> list[Situation]:
    """Claude, answering with the assessment; the situations it was asked about."""
    seen: list[Situation] = []

    def fake(situation: Situation) -> Assessment:
        seen.append(situation)
        return make_assessment()

    monkeypatch.setattr(assistant, "assess", fake)
    return seen


@pytest.fixture
def fake_jira(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Jira, creating ROT-1400; the titles and descriptions it got."""
    created: list[tuple[str, str]] = []

    def create_issue(self: JiraClient, title: str, description: str) -> Issue:
        created.append((title, description))
        return Issue("ROT-1400", "https://jira.test/browse/ROT-1400")

    monkeypatch.setattr(JiraClient, "create_issue", create_issue)
    return created


def test_assess_button_only_with_an_api_key(
    admin_client: Client, diagnosed: Case, case_url: str, settings: Any
) -> None:
    settings.ANTHROPIC_API_KEY = ""
    assert b'value="assess"' not in admin_client.get(case_url).content

    settings.ANTHROPIC_API_KEY = "sk-test"
    assert b'value="assess"' in admin_client.get(case_url).content


def test_assess_records_claudes_assessment(
    claude_on: Any,
    diagnosed: Case,
    answer: Callable[..., Any],
    fake_assess: list[Situation],
    make_assessment: Callable[..., Assessment],
) -> None:
    response = answer("", action="assess")

    diagnosed.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert diagnosed.assessment == make_assessment().as_dict()
    assert diagnosed.assessment_model == "claude-sonnet-5-5"
    assert diagnosed.assessed_at is not None
    assert fake_assess[0].answers == {"when": "now", "symptom": "dead", "power": "no"}


def test_assess_does_nothing_without_an_api_key(
    settings: Any, diagnosed: Case, answer: Callable[..., Any], fake_assess: list[Situation]
) -> None:
    settings.ANTHROPIC_API_KEY = ""

    answer("", action="assess")

    diagnosed.refresh_from_db()
    assert diagnosed.assessment == {} and fake_assess == []


def test_assess_waits_for_the_last_answer(
    claude_on: Any, case: Case, answer: Callable[..., Any], fake_assess: list[Situation]
) -> None:
    answer("", action="assess")

    case.refresh_from_db()
    assert case.assessment == {} and fake_assess == []


def test_assess_when_claude_is_unavailable(
    claude_on: Any,
    admin_client: Client,
    diagnosed: Case,
    case_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(situation: Situation) -> Assessment:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://claude.test"))

    monkeypatch.setattr(assistant, "assess", unavailable)

    response = admin_client.post(case_url, {"action": "assess"}, follow=True)

    diagnosed.refresh_from_db()
    assert diagnosed.assessment == {}
    assert b"Claude couldn&#x27;t assess the case" in response.content


def test_assessment_shown_on_the_case(
    admin_client: Client, assessed: Case, case_url: str, jira_on: Any
) -> None:
    content = admin_client.get(case_url).content

    assert b"Claude's assessment" in content
    assert b"Power cut on site" in content
    assert b"needs the tech team" in content
    assert b"Ask the site to check the breaker." in content
    assert b'value="escalate" class="default"' in content


def test_assessment_that_support_can_handle(
    admin_client: Client,
    diagnosed: Case,
    case_url: str,
    jira_on: Any,
    make_assessment: Callable[..., Assessment],
    now: datetime,
) -> None:
    assessment = make_assessment(needs_escalation=False, agrees_with_rules=False, support_steps=[])
    diagnosed.record_assessment(assessment, "claude-sonnet-5-5", now)

    content = admin_client.get(case_url).content

    assert b"support can handle it" in content
    assert b"disagrees with the diagnosis above" in content
    assert b'value="escalate">' in content  # still possible, not the default


def test_escalate_creates_the_jira_issue(
    jira_on: Any,
    admin_client: Client,
    assessed: Case,
    case_url: str,
    fake_jira: list[tuple[str, str]],
) -> None:
    response = admin_client.post(case_url, {"action": "escalate"}, follow=True)

    assessed.refresh_from_db()
    assert (assessed.jira_issue, assessed.jira_issue_url) == (
        "ROT-1400",
        "https://jira.test/browse/ROT-1400",
    )
    title, description = fake_jira[0]
    assert title == "EOS-1 offline without power"
    assert description.startswith("Offline since 10:02.\nNo power on site.")
    assert f"http://testserver{case_url}" in description
    assert "Support ticket: none" in description
    assert assessed.summary in description
    assert b"Created ROT-1400." in response.content
    assert b'href="https://jira.test/browse/ROT-1400"' in response.content


def test_escalate_only_once(
    jira_on: Any, assessed: Case, answer: Callable[..., Any], fake_jira: list[tuple[str, str]]
) -> None:
    answer("", action="escalate")
    answer("", action="escalate")

    assert len(fake_jira) == 1


def test_escalate_needs_an_assessment(
    jira_on: Any, diagnosed: Case, answer: Callable[..., Any], fake_jira: list[tuple[str, str]]
) -> None:
    answer("", action="escalate")

    assert fake_jira == []


def test_escalate_does_nothing_without_jira(
    settings: Any, assessed: Case, answer: Callable[..., Any], fake_jira: list[tuple[str, str]]
) -> None:
    settings.JIRA_API_TOKEN = ""

    answer("", action="escalate")

    assert fake_jira == []


def test_escalate_when_jira_refuses(
    jira_on: Any,
    admin_client: Client,
    assessed: Case,
    case_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: JiraClient, title: str, description: str) -> Issue:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(JiraClient, "create_issue", refuse)

    response = admin_client.post(case_url, {"action": "escalate"}, follow=True)

    assessed.refresh_from_db()
    assert assessed.jira_issue == ""
    assert b"Jira refused the ticket" in response.content


def test_back_drops_the_assessment(assessed: Case, answer: Callable[..., Any]) -> None:
    answer("", action="back")

    assessed.refresh_from_db()
    assert assessed.assessment == {}


def test_restart_drops_the_assessment(assessed: Case, answer: Callable[..., Any]) -> None:
    answer("", action="restart")

    assessed.refresh_from_db()
    assert assessed.assessment == {}


def test_rediagnose_keeps_the_assessment(assessed: Case, answer: Callable[..., Any]) -> None:
    answer("", action="rediagnose")

    assessed.refresh_from_db()
    assert assessed.assessment
