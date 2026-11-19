"""The workflow engine: which question comes next, and the diagnosis rules."""

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import Any

import pytest

from diagnostics.checks import ERROR_CODE_ADVICE
from diagnostics.checks import REJECTION_ADVICE
from diagnostics.checks import Finding
from diagnostics.checks import Severity
from diagnostics.checks import run_checks
from diagnostics.snapshot import LOOKBACK
from diagnostics.snapshot import Snapshot
from diagnostics.workflow import EARLIER_LOOKBACK
from diagnostics.workflow import Confidence
from diagnostics.workflow import Situation
from diagnostics.workflow import asked
from diagnostics.workflow import diagnose
from diagnostics.workflow import lookback
from diagnostics.workflow import next_question
from diagnostics.workflow import without_last_answer
from services.ocpp.models import ConnectorV16


@pytest.fixture
def make_situation(
    make_snapshot: Callable[..., Snapshot], now: datetime
) -> Callable[..., Situation]:
    """A Situation from snapshot overrides and answers; findings from the real checks."""

    def factory(
        answers: dict[str, str] | None = None,
        findings: list[Finding] | None = None,
        **snapshot: Any,
    ) -> Situation:
        built = make_snapshot(**snapshot)
        checked = run_checks(built, now) if findings is None else findings
        return Situation(built, checked, answers or {}, now)

    return factory


@pytest.fixture
def two_connectors(make_connector: Callable[..., ConnectorV16]) -> list[ConnectorV16]:
    return [make_connector(index=1), make_connector(index=2, status="charging")]


@pytest.fixture
def base_answers() -> dict[str, str]:
    """What every case answers first."""
    return {"when": "now"}


# --- Questions ---


def test_next_question_starts_with_when(make_situation: Callable[..., Situation]) -> None:
    question = next_question(make_situation())

    assert question is not None and question.key == "when"


def test_next_question_skips_the_connector_with_a_single_one(
    make_situation: Callable[..., Situation], base_answers: dict[str, str]
) -> None:
    question = next_question(make_situation(base_answers))

    assert question is not None and question.key == "symptom"


def test_next_question_asks_which_connector_when_several(
    make_situation: Callable[..., Situation],
    base_answers: dict[str, str],
    two_connectors: list[ConnectorV16],
) -> None:
    question = next_question(make_situation(base_answers, connectors=two_connectors))

    assert question is not None and question.key == "connector"
    assert [value for value, _ in question.choices] == ["1", "2", "unknown"]
    assert "now charging" in question.choices[1][1]


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ({"symptom": "dead"}, "power"),
        ({"symptom": "refused"}, "start"),
        ({"symptom": "refused", "start": "badge"}, "badge"),
        ({"symptom": "refused", "start": "badge", "badge": "B1"}, "badge_reaction"),
        ({"symptom": "error"}, "screen"),
        ({"symptom": "no_charge", "start": "swish_app"}, "other_chargers"),
        ({"symptom": "stops", "start": "unknown"}, "other_chargers"),
        ({"symptom": "cable_stuck"}, None),
        ({"symptom": "refused", "start": "swish_app"}, None),
    ],
)
def test_next_question_follows_the_answers(
    make_situation: Callable[..., Situation],
    base_answers: dict[str, str],
    answers: dict[str, str],
    expected: str | None,
) -> None:
    question = next_question(make_situation(base_answers | answers))

    assert (question.key if question else None) == expected


def test_next_question_asks_about_power_when_the_charger_is_offline(
    make_situation: Callable[..., Situation],
    make_charge_point: Callable[..., Any],
    base_answers: dict[str, str],
) -> None:
    situation = make_situation(
        base_answers | {"symptom": "refused"}, charge_point=make_charge_point(connected=False)
    )

    question = next_question(situation)

    assert question is not None and question.key == "power"


def test_next_question_skips_the_badge_reaction_when_the_badge_was_refused(
    make_situation: Callable[..., Situation],
    make_rejection: Callable[..., Any],
    base_answers: dict[str, str],
) -> None:
    answers = base_answers | {"symptom": "refused", "start": "badge", "badge": "badge9"}

    assert next_question(make_situation(answers, rejected_rfids=[make_rejection()])) is None


def test_next_question_skips_the_badge_reaction_when_a_session_used_the_badge(
    make_situation: Callable[..., Situation],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
    base_answers: dict[str, str],
) -> None:
    connector = make_connector()
    answers = base_answers | {"symptom": "refused", "start": "badge", "badge": "badge1"}
    situation = make_situation(
        answers,
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id)],
    )

    assert next_question(situation) is None


def test_without_last_answer_drops_the_latest_in_question_order() -> None:
    answers = {"symptom": "dead", "when": "now", "power": "no"}

    assert without_last_answer(answers) == {"symptom": "dead", "when": "now"}


def test_without_last_answer_with_no_answers() -> None:
    assert without_last_answer({}) == {}


def test_asked_lists_questions_and_readable_answers(
    make_situation: Callable[..., Situation], base_answers: dict[str, str]
) -> None:
    answers = base_answers | {"symptom": "refused", "start": "badge", "badge": ""}

    assert asked(make_situation(answers)) == [
        ("When did it happen?", "Right now, or in the last hour"),
        ("What does the customer see?", "The badge or the app is refused"),
        ("How did the customer try to start charging?", "An RFID badge"),
        ("What's the number printed on the badge?", "—"),
    ]


@pytest.mark.parametrize(
    ("when", "expected"), [("now", LOOKBACK), ("today", LOOKBACK), ("earlier", EARLIER_LOOKBACK)]
)
def test_lookback_follows_when(when: str, expected: timedelta) -> None:
    assert lookback({"when": when}) == expected


def test_situation_connector_is_the_one_picked(
    make_situation: Callable[..., Situation], two_connectors: list[ConnectorV16]
) -> None:
    situation = make_situation({"connector": "2"}, connectors=two_connectors)

    assert situation.connector is two_connectors[1]


def test_situation_connector_unknown(
    make_situation: Callable[..., Situation], two_connectors: list[ConnectorV16]
) -> None:
    assert make_situation({"connector": "unknown"}, connectors=two_connectors).connector is None


def test_situation_transactions_on_every_connector_when_unknown(
    make_situation: Callable[..., Situation],
    two_connectors: list[ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    transactions = [make_transaction(connector_id=c.id) for c in two_connectors]

    situation = make_situation(connectors=two_connectors, transactions=transactions)

    assert len(situation.transactions()) == 2


# --- Diagnosis ---


@pytest.fixture
def diagnosis_of(make_situation: Callable[..., Situation]) -> Callable[..., Any]:
    def run(answers: dict[str, str] | None = None, **snapshot: Any) -> Any:
        return diagnose(make_situation({"when": "now"} | (answers or {}), **snapshot))

    return run


def test_diagnose_not_activated(
    diagnosis_of: Callable[..., Any], make_charge_point: Callable[..., Any]
) -> None:
    diagnosis = diagnosis_of(charge_point=make_charge_point(is_active=False))

    assert diagnosis.likely_cause == "The charger isn't activated on the platform"
    assert diagnosis.confidence == Confidence.HIGH


@pytest.mark.parametrize(
    ("power", "cause", "confidence"),
    [
        ("no", "No power at the charger", Confidence.HIGH),
        ("yes", "The charger has power but no network connection", Confidence.HIGH),
        ("unknown", "The charger is offline", Confidence.MEDIUM),
    ],
)
def test_diagnose_offline(
    diagnosis_of: Callable[..., Any],
    make_charge_point: Callable[..., Any],
    power: str,
    cause: str,
    confidence: Confidence,
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "dead", "power": power}, charge_point=make_charge_point(connected=False)
    )

    assert (diagnosis.likely_cause, diagnosis.confidence) == (cause, confidence)


def test_diagnose_charger_out_of_service(
    diagnosis_of: Callable[..., Any], make_charge_point: Callable[..., Any]
) -> None:
    diagnosis = diagnosis_of(charge_point=make_charge_point(availability="inoperative"))

    assert diagnosis.likely_cause == "The charger was set out of service"


def test_diagnose_connector_out_of_service(
    diagnosis_of: Callable[..., Any], make_connector: Callable[..., ConnectorV16]
) -> None:
    diagnosis = diagnosis_of(connectors=[make_connector(availability="inoperative")])

    assert diagnosis.likely_cause == "Connector 1 was set out of service"


def test_diagnose_connector_faulted(
    diagnosis_of: Callable[..., Any], make_connector: Callable[..., ConnectorV16]
) -> None:
    diagnosis = diagnosis_of(
        connectors=[make_connector(status="faulted", error_code="ground_failure")]
    )

    assert diagnosis.likely_cause == "Connector 1 is faulted (ground_failure)"
    assert diagnosis.customer_reply == ERROR_CODE_ADVICE["ground_failure"][1]


def test_diagnose_connector_faulted_without_code(
    diagnosis_of: Callable[..., Any], make_connector: Callable[..., ConnectorV16]
) -> None:
    diagnosis = diagnosis_of(connectors=[make_connector(status="faulted", error_code=None)])

    assert diagnosis.likely_cause == "Connector 1 is faulted (other_error)"


def test_diagnose_cable_stuck_with_an_open_session(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "cable_stuck"},
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id, status="ONGOING")],
    )

    assert diagnosis.likely_cause == "The connector lock didn't release"
    assert diagnosis.confidence == Confidence.HIGH
    assert diagnosis.actions[0].startswith("Stop the open session")


def test_diagnose_cable_stuck_without_session(diagnosis_of: Callable[..., Any]) -> None:
    diagnosis = diagnosis_of({"symptom": "cable_stuck"})

    assert diagnosis.confidence == Confidence.MEDIUM
    assert diagnosis.actions[0] == "Send UnlockConnector for the connector."


@pytest.mark.parametrize(
    ("badge", "confidence"), [("BADGE9", Confidence.HIGH), ("", Confidence.MEDIUM)]
)
def test_diagnose_badge_refused(
    diagnosis_of: Callable[..., Any],
    make_rejection: Callable[..., Any],
    badge: str,
    confidence: Confidence,
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "refused", "start": "badge", "badge": badge},
        rejected_rfids=[make_rejection(reason_kind="PRIVATE_CHARGER")],
    )

    assert diagnosis.likely_cause == "The badge BADGE9 is refused (PRIVATE_CHARGER)"
    assert diagnosis.confidence == confidence
    assert diagnosis.customer_reply == REJECTION_ADVICE["PRIVATE_CHARGER"][1]


def test_diagnose_badge_refused_for_an_unknown_reason(
    diagnosis_of: Callable[..., Any], make_rejection: Callable[..., Any]
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "refused", "start": "other_app"},
        rejected_rfids=[make_rejection(reason_kind="SOMETHING_NEW")],
    )

    assert diagnosis.actions == [REJECTION_ADVICE["UNKNOWN"][0]]


@pytest.mark.parametrize(
    ("reaction", "cause"),
    [
        ("no", "The charger doesn't read the badge"),
        ("yes", "The badge was read but the request never reached us"),
        ("unknown", "No fault visible in the backend"),
    ],
)
def test_diagnose_badge_never_heard_of(
    diagnosis_of: Callable[..., Any], reaction: str, cause: str
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "refused", "start": "badge", "badge": "B1", "badge_reaction": reaction}
    )

    assert diagnosis.likely_cause == cause


def test_diagnose_app_start_never_arrived(diagnosis_of: Callable[..., Any]) -> None:
    diagnosis = diagnosis_of({"symptom": "refused", "start": "swish_app"})

    assert diagnosis.likely_cause == "The start from the app never reached the charger"


def test_diagnose_app_start_that_made_a_session_is_not_lost(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "refused", "start": "swish_app"},
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id)],
    )

    assert diagnosis.likely_cause == "No fault visible in the backend"


def test_diagnose_power_held_back(
    diagnosis_of: Callable[..., Any], make_connector: Callable[..., ConnectorV16]
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "no_charge", "start": "badge", "badge": "B1", "other_chargers": "yes"},
        connectors=[make_connector(status="suspended_evse")],
    )

    assert diagnosis.likely_cause.startswith("The charger is holding back power")


@pytest.mark.parametrize(
    ("status", "confidence"), [("suspended_ev", Confidence.HIGH), ("charging", Confidence.MEDIUM)]
)
def test_diagnose_car_side_when_it_fails_elsewhere_too(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    status: str,
    confidence: Confidence,
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "no_charge", "start": "swish_app", "other_chargers": "no"},
        connectors=[make_connector(status=status)],
    )

    assert (diagnosis.likely_cause, diagnosis.confidence) == (
        "A problem on the car's side",
        confidence,
    )


def test_diagnose_car_refusing_power(
    diagnosis_of: Callable[..., Any], make_connector: Callable[..., ConnectorV16]
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "no_charge", "start": "swish_app", "other_chargers": "unknown"},
        connectors=[make_connector(status="suspended_ev")],
    )

    assert diagnosis.likely_cause == "The car isn't taking power"


def test_diagnose_session_stopped_early(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "stops", "start": "swish_app", "other_chargers": "yes"},
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id, reason="power_loss")],
    )

    assert diagnosis.likely_cause == "The last session was stopped (power_loss)"
    assert "restarted or lost power" in diagnosis.actions[0]


def test_diagnose_session_stopped_without_reason(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "stops", "start": "swish_app", "other_chargers": "unknown"},
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id, reason=None)],
    )

    assert diagnosis.likely_cause == "The last session was stopped (unknown)"


def test_diagnose_no_energy_for_a_car_that_charges_elsewhere(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "no_charge", "start": "swish_app", "other_chargers": "yes"},
        connectors=[connector],
        transactions=[make_transaction(connector_id=connector.id, energy_delivered=0.0)],
    )

    assert diagnosis.likely_cause == "The charger doesn't deliver energy to this car"


def test_diagnose_car_complaint_with_nothing_to_go_on(diagnosis_of: Callable[..., Any]) -> None:
    diagnosis = diagnosis_of({"symptom": "stops", "start": "swish_app", "other_chargers": "yes"})

    assert diagnosis.likely_cause == "No fault visible in the backend"


def test_diagnose_old_session_still_open(
    diagnosis_of: Callable[..., Any],
    make_connector: Callable[..., ConnectorV16],
    make_transaction: Callable[..., Any],
    now: datetime,
) -> None:
    connector = make_connector()
    diagnosis = diagnosis_of(
        {"symptom": "other", "start": "unknown"},
        connectors=[connector],
        transactions=[
            make_transaction(
                connector_id=connector.id, status="ONGOING", started_at=now - timedelta(days=3)
            )
        ],
    )

    assert diagnosis.likely_cause == "An old session is still open and blocks the connector"


@pytest.mark.parametrize(
    ("screen", "cause"),
    [("E42 RCD", "The charger shows an error: E42 RCD"), ("", "The charger shows an error")],
)
def test_diagnose_error_on_screen(
    diagnosis_of: Callable[..., Any], screen: str, cause: str
) -> None:
    diagnosis = diagnosis_of({"symptom": "error", "screen": screen})

    assert (diagnosis.likely_cause, diagnosis.confidence) == (cause, Confidence.LOW)


@pytest.mark.parametrize(
    ("severity", "confidence"),
    [(Severity.PROBLEM, Confidence.MEDIUM), (Severity.WARNING, Confidence.LOW)],
)
def test_diagnose_falls_back_on_the_worst_finding(
    make_situation: Callable[..., Situation], severity: Severity, confidence: Confidence
) -> None:
    finding = Finding(severity, "Something odd", "evidence", "do this", "")
    situation = make_situation({"symptom": "other", "start": "unknown"}, findings=[finding])

    diagnosis = diagnose(situation)

    assert (diagnosis.likely_cause, diagnosis.confidence) == ("Something odd", confidence)
    assert diagnosis.actions == ["do this"]
    assert diagnosis.customer_reply.startswith("We've found something unusual")


def test_diagnose_finding_without_action(make_situation: Callable[..., Situation]) -> None:
    finding = Finding(Severity.WARNING, "Odd", "evidence", "", "Reply")

    diagnosis = diagnose(make_situation({"symptom": "other"}, findings=[finding]))

    assert (diagnosis.actions, diagnosis.customer_reply) == ([], "Reply")


def test_diagnose_nothing_found(diagnosis_of: Callable[..., Any]) -> None:
    diagnosis = diagnosis_of({"symptom": "other", "start": "unknown"})

    assert diagnosis.likely_cause == "No fault visible in the backend"
    assert diagnosis.confidence == Confidence.LOW


def test_diagnose_writes_the_ticket_summary(
    diagnosis_of: Callable[..., Any],
    make_charge_point: Callable[..., Any],
    make_incident: Callable[..., Any],
) -> None:
    diagnosis = diagnosis_of(
        {"symptom": "dead", "power": "no"},
        charge_point=make_charge_point(connected=False, charger_name=None, customer_name=None),
        incidents=[make_incident()],
    )

    lines = diagnosis.summary.splitlines()
    assert lines[0] == "Charger: FR*SWI*CP001 (no name, no customer), tenant public"
    assert lines[1] == "Connector: Connector 1"
    assert "- What does the customer see? Nothing happens: the screen or lights are off" in lines
    assert any(line.startswith("- [problem] Charger offline: Not connected") for line in lines)
    assert "Likely cause (high confidence): No power at the charger" in lines
    assert lines[-1].startswith("- If the supply is fine")


def test_diagnose_summary_without_connector(
    make_situation: Callable[..., Situation], two_connectors: list[ConnectorV16]
) -> None:
    diagnosis = diagnose(make_situation({"connector": "unknown"}, connectors=two_connectors))

    assert "Connector: not known" in diagnosis.summary
