import json
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from typing import Any

import anthropic
import httpx2
import pytest

from diagnostics.assistant import ASSESSMENT_SCHEMA
from diagnostics.assistant import REQUEST_TIMEOUT_SECONDS
from diagnostics.assistant import TOOL_NAME
from diagnostics.assistant import Assessment
from diagnostics.assistant import assess
from diagnostics.assistant import case_context
from diagnostics.assistant import enabled
from diagnostics.assistant import make_client
from diagnostics.assistant import mask
from diagnostics.assistant import tokens
from diagnostics.checks import run_checks
from diagnostics.snapshot import Snapshot
from diagnostics.workflow import Situation


@pytest.fixture
def make_situation(now: datetime) -> Callable[..., Situation]:
    def factory(snapshot: Snapshot, answers: dict[str, str] | None = None) -> Situation:
        return Situation(snapshot, run_checks(snapshot, now), answers or {}, now)

    return factory


@pytest.fixture
def badge_snapshot(
    make_snapshot: Callable[..., Snapshot],
    make_charge_point: Callable[..., Any],
    make_rejection: Callable[..., Any],
    make_transaction: Callable[..., Any],
) -> Snapshot:
    return make_snapshot(
        charge_point=make_charge_point(iccid="8933000000000000001", ip_address="10.0.0.7"),
        rejected_rfids=[make_rejection(id_token="04A1B2C3D4")],
        transactions=[make_transaction(id_tag="04FFEEDDCC", email="driver@example.com")],
    )


@pytest.fixture
def assessment_payload(make_assessment: Callable[..., Assessment]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": TOOL_NAME,
                "input": make_assessment().as_dict(),
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 300},
    }


def test_mask_keeps_the_last_characters() -> None:
    assert mask("04A1B2C3D4") == "...C3D4"


def test_enabled_needs_an_api_key(settings: Any) -> None:
    settings.ANTHROPIC_API_KEY = ""
    assert enabled() is False

    settings.ANTHROPIC_API_KEY = "sk-test"
    assert enabled() is True


def test_case_context_has_the_whole_case(
    make_situation: Callable[..., Situation],
    make_snapshot: Callable[..., Snapshot],
    make_charge_point: Callable[..., Any],
    make_incident: Callable[..., Any],
) -> None:
    snapshot = make_snapshot(
        charge_point=make_charge_point(identity="EOS-1", connected=False),
        incidents=[make_incident()],
    )

    context = json.loads(case_context(make_situation(snapshot, {"when": "now", "power": "no"})))

    assert context["charger"]["identity"] == "EOS-1"
    assert context["customer_connector"] == 1
    assert len(context["connectors"]) == len(context["incidents"]) == 1
    assert context["findings"][0]["title"] == "Charger offline"
    assert {"question": "When did it happen?", "answer": "Right now, or in the last hour"} in (
        context["questions_and_answers"]
    )
    assert context["rule_based_diagnosis"]["likely_cause"] == "No power at the charger"
    assert context["looking_back_days"] == 1


def test_case_context_without_a_known_connector(
    make_situation: Callable[..., Situation],
    make_snapshot: Callable[..., Snapshot],
    make_connector: Callable[..., Any],
) -> None:
    snapshot = make_snapshot(connectors=[make_connector(index=1), make_connector(index=2)])

    context = json.loads(case_context(make_situation(snapshot)))

    assert context["customer_connector"] is None


def test_case_context_leaves_out_personal_data(
    make_situation: Callable[..., Situation], badge_snapshot: Snapshot
) -> None:
    text = case_context(make_situation(badge_snapshot))

    for secret in ["driver@example.com", "8933000000000000001", "10.0.0.7"]:
        assert secret not in text
    context = json.loads(text)
    assert "email" not in context["sessions"][0]
    assert "iccid" not in context["charger"]


def test_case_context_masks_badges_everywhere(
    make_situation: Callable[..., Situation], badge_snapshot: Snapshot
) -> None:
    # The rep typed the refused badge: it shows up in the answers and in the rules' texts too.
    answers = {"when": "now", "symptom": "refused", "start": "badge", "badge": "04A1B2C3D4"}

    text = case_context(make_situation(badge_snapshot, answers))

    assert "04A1B2C3D4" not in text and "04FFEEDDCC" not in text
    context = json.loads(text)
    assert context["refused_badges"][0]["id_token"] == "...C3D4"
    assert context["sessions"][0]["id_tag"] == "...DDCC"
    assert "...C3D4" in context["rule_based_diagnosis"]["likely_cause"]


def test_tokens_skips_short_badges(badge_snapshot: Snapshot) -> None:
    # Masking a badge no longer than the visible part would show it whole anyway, and replacing
    # a few characters everywhere would garble the rest of the text.
    assert tokens(badge_snapshot, {"badge": "B42"}) == {"04A1B2C3D4", "04FFEEDDCC"}


@pytest.fixture
def claude(assessment_payload: dict[str, Any]) -> tuple[anthropic.Anthropic, list[httpx2.Request]]:
    """A client whose API answers with the assessment, and the requests it got."""
    requests: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(HTTPStatus.OK, json=assessment_payload)

    client = anthropic.Anthropic(
        api_key="sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(answer))
    )
    return client, requests


def test_make_client_uses_the_settings(settings: Any) -> None:
    settings.ANTHROPIC_API_KEY = "sk-test"

    client = make_client()

    assert (client.api_key, client.timeout) == ("sk-test", REQUEST_TIMEOUT_SECONDS)


def test_assess_asks_claude_for_the_assessment(
    settings: Any,
    claude: tuple[anthropic.Anthropic, list[httpx2.Request]],
    make_situation: Callable[..., Situation],
    make_snapshot: Callable[..., Snapshot],
    make_assessment: Callable[..., Assessment],
) -> None:
    settings.ANTHROPIC_MODEL = "claude-sonnet-5-5"
    client, requests = claude

    assessment = assess(make_situation(make_snapshot()), client)

    assert assessment == make_assessment()
    request = json.loads(requests[-1].content)
    assert request["model"] == "claude-sonnet-5-5"
    assert request["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert request["tools"][0]["input_schema"] == ASSESSMENT_SCHEMA
    assert json.loads(request["messages"][0]["content"])["charger"]["identity"]
