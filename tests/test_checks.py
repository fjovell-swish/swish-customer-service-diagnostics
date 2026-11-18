from datetime import datetime
from datetime import timedelta

import pytest

from diagnostics.checks import ago
from diagnostics.checks import check_availability
from diagnostics.checks import check_connection
from diagnostics.checks import check_connection_stability
from diagnostics.checks import check_connectors
from diagnostics.checks import check_firmware
from diagnostics.checks import check_registration
from diagnostics.checks import check_rejected_badges
from diagnostics.checks import check_transactions
from diagnostics.checks import ERROR_CODE_ADVICE
from diagnostics.checks import FLAPPING_DISCONNECTS
from diagnostics.checks import REJECTION_ADVICE
from diagnostics.checks import run_checks
from diagnostics.checks import Severity
from diagnostics.checks import verdict


def test_run_checks_healthy_charger(make_snapshot, now: datetime) -> None:
    findings = run_checks(make_snapshot(), now)

    assert [finding.title for finding in findings] == ["Online"]
    assert verdict(findings)[0] == Severity.OK


def test_run_checks_sorts_worst_first(make_snapshot, make_charge_point, make_connector, now: datetime) -> None:
    snapshot = make_snapshot(
        charge_point=make_charge_point(connected=False),
        connectors=[make_connector(status="suspended_ev")],
    )

    findings = run_checks(snapshot, now)

    assert [finding.severity for finding in findings] == [Severity.PROBLEM, Severity.WARNING]
    assert verdict(findings)[0] == Severity.PROBLEM


def test_registration_inactive_charger(make_snapshot, make_charge_point, now: datetime) -> None:
    findings = check_registration(make_snapshot(charge_point=make_charge_point(is_active=False)), now)

    assert findings[0].severity == Severity.PROBLEM
    assert findings[0].title == "Charger not activated"


def test_registration_active_charger(make_snapshot, now: datetime) -> None:
    assert check_registration(make_snapshot(), now) == []


def test_connection_offline_reports_since_last_disconnect(
    make_snapshot, make_charge_point, make_incident, now: datetime
) -> None:
    snapshot = make_snapshot(
        charge_point=make_charge_point(connected=False),
        incidents=[make_incident(started_at=now - timedelta(hours=3))],
    )

    finding = check_connection(snapshot, now)[0]

    assert finding.severity == Severity.PROBLEM
    assert finding.title == "Charger offline"
    assert "since 3 h 0 min ago" in finding.evidence
    assert finding.customer_reply


def test_connection_silent_when_heartbeat_stale(make_snapshot, make_charge_point, now: datetime) -> None:
    snapshot = make_snapshot(charge_point=make_charge_point(last_heartbeat=now - timedelta(minutes=30)))

    finding = check_connection(snapshot, now)[0]

    assert finding.title == "Connected but silent"
    assert finding.severity == Severity.PROBLEM


def test_connection_silent_without_any_heartbeat(make_snapshot, make_charge_point, now: datetime) -> None:
    snapshot = make_snapshot(charge_point=make_charge_point(last_heartbeat=None))

    assert check_connection(snapshot, now)[0].title == "Connected but silent"


def test_connection_stability_flags_flapping(make_snapshot, make_incident, now: datetime) -> None:
    incidents = [make_incident() for _ in range(FLAPPING_DISCONNECTS)]

    findings = check_connection_stability(make_snapshot(incidents=incidents), now)

    assert findings[0].title == "Unstable connection"


def test_connection_stability_ignores_connect_events(make_snapshot, make_incident, now: datetime) -> None:
    incidents = [make_incident(event="connected") for _ in range(FLAPPING_DISCONNECTS)]

    assert check_connection_stability(make_snapshot(incidents=incidents), now) == []


def test_availability_inoperative_charger_and_connector(
    make_snapshot, make_charge_point, make_connector, now: datetime
) -> None:
    snapshot = make_snapshot(
        charge_point=make_charge_point(availability="inoperative"),
        connectors=[make_connector(index=2, availability="inoperative")],
    )

    titles = [finding.title for finding in check_availability(snapshot, now)]

    assert titles == ["Charger set to inoperative", "Connector 2 set to inoperative"]


@pytest.mark.parametrize("error_code", sorted(ERROR_CODE_ADVICE))
def test_connectors_faulted_uses_error_code_advice(make_snapshot, make_connector, now: datetime, error_code) -> None:
    snapshot = make_snapshot(connectors=[make_connector(status="faulted", error_code=error_code)])

    finding = check_connectors(snapshot, now)[0]

    assert finding.severity == Severity.PROBLEM
    assert (finding.action, finding.customer_reply) == ERROR_CODE_ADVICE[error_code]


def test_connectors_faulted_without_error_code(make_snapshot, make_connector, now: datetime) -> None:
    snapshot = make_snapshot(connectors=[make_connector(status="faulted", error_code=None)])

    assert check_connectors(snapshot, now)[0].title == "Connector 1 faulted: other_error"


def test_connectors_error_code_while_available_is_a_warning(make_snapshot, make_connector, now: datetime) -> None:
    snapshot = make_snapshot(connectors=[make_connector(error_code="weak_signal")])

    finding = check_connectors(snapshot, now)[0]

    assert finding.severity == Severity.WARNING
    assert finding.title == "Connector 1 reports weak_signal"


@pytest.mark.parametrize(
    ("status", "title"),
    [
        ("unavailable", "Connector 1 unavailable"),
        ("suspended_ev", "Connector 1: the car isn't taking power"),
        ("suspended_evse", "Connector 1: the charger is holding back power"),
    ],
)
def test_connectors_status(make_snapshot, make_connector, now: datetime, status: str, title: str) -> None:
    snapshot = make_snapshot(connectors=[make_connector(status=status)])

    assert check_connectors(snapshot, now)[0].title == title


def test_connectors_preparing_too_long(make_snapshot, make_connector, now: datetime) -> None:
    snapshot = make_snapshot(connectors=[make_connector(status="preparing", updated_at=now - timedelta(minutes=40))])

    assert check_connectors(snapshot, now)[0].title == "Connector 1 stuck in preparing"


def test_connectors_preparing_briefly_is_fine(make_snapshot, make_connector, now: datetime) -> None:
    snapshot = make_snapshot(connectors=[make_connector(status="preparing", updated_at=now - timedelta(minutes=2))])

    assert check_connectors(snapshot, now) == []


def test_connectors_none_known(make_snapshot, now: datetime) -> None:
    assert check_connectors(make_snapshot(connectors=[]), now)[0].title == "No connectors known"


def test_rejected_badges_grouped_per_badge_and_reason(make_snapshot, make_rejection, now: datetime) -> None:
    rejections = [
        make_rejection(),
        make_rejection(),
        make_rejection(reason_kind="PRIVATE_CHARGER"),
    ]

    findings = check_rejected_badges(make_snapshot(rejected_rfids=rejections), now)

    assert [finding.title for finding in findings] == [
        "Badge BADGE9 refused: RFID_DOES_NOT_EXIST",
        "Badge BADGE9 refused: PRIVATE_CHARGER",
    ]
    assert findings[0].evidence.startswith("Refused 2×")
    assert findings[1].customer_reply == REJECTION_ADVICE["PRIVATE_CHARGER"][1]


def test_rejected_badges_unknown_reason_falls_back(make_snapshot, make_rejection, now: datetime) -> None:
    findings = check_rejected_badges(make_snapshot(rejected_rfids=[make_rejection(reason_kind="NEW_KIND")]), now)

    assert findings[0].action == REJECTION_ADVICE["UNKNOWN"][0]


def test_transactions_pending_without_energy(make_snapshot, make_connector, make_transaction, now: datetime) -> None:
    connector = make_connector()
    transaction = make_transaction(
        status="PENDING", started_at=now - timedelta(minutes=20), ended_at=None, connector_id=connector.id
    )

    findings = check_transactions(make_snapshot(connectors=[connector], transactions=[transaction]), now)

    assert findings[0].title == "Session #1234 on Connector 1 started but no energy"


def test_transactions_stuck_ongoing(make_snapshot, make_transaction, now: datetime) -> None:
    transaction = make_transaction(status="ONGOING", started_at=now - timedelta(days=3), ended_at=None)

    finding = check_transactions(make_snapshot(transactions=[transaction]), now)[0]

    assert finding.severity == Severity.PROBLEM
    assert finding.title == "Session #1234 on Unknown connector still open after 3 days"


def test_transactions_recent_ongoing_is_fine(make_snapshot, make_transaction, now: datetime) -> None:
    transaction = make_transaction(status="ONGOING", started_at=now - timedelta(hours=1), ended_at=None)

    assert check_transactions(make_snapshot(transactions=[transaction]), now) == []


def test_transactions_failed(make_snapshot, make_transaction, now: datetime) -> None:
    findings = check_transactions(make_snapshot(transactions=[make_transaction(status="FAILED")]), now)

    assert findings[0].title.endswith("failed")


def test_transactions_finished_without_energy(make_snapshot, make_transaction, now: datetime) -> None:
    transaction = make_transaction(energy_delivered=0.0, reason="ev_disconnected")

    finding = check_transactions(make_snapshot(transactions=[transaction]), now)[0]

    assert finding.title.endswith("ended with no energy")
    assert "unplugged" in finding.customer_reply


def test_transactions_finished_with_energy_is_fine(make_snapshot, make_transaction, now: datetime) -> None:
    assert check_transactions(make_snapshot(transactions=[make_transaction()]), now) == []


def test_firmware_failed_update(make_snapshot, make_firmware, now: datetime) -> None:
    firmware = make_firmware(status="download_failed", error="404")

    finding = check_firmware(make_snapshot(firmwares=[firmware]), now)[0]

    assert finding.title == "Last firmware update download_failed"
    assert "404" in finding.evidence


def test_firmware_installing(make_snapshot, make_firmware, now: datetime) -> None:
    findings = check_firmware(make_snapshot(firmwares=[make_firmware(status="installing")]), now)

    assert findings[0].severity == Severity.INFO


def test_firmware_installed_is_fine(make_snapshot, make_firmware, now: datetime) -> None:
    assert check_firmware(make_snapshot(firmwares=[make_firmware()]), now) == []


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=-5), "just now"),
        (timedelta(seconds=42), "42 s ago"),
        (timedelta(minutes=7), "7 min ago"),
        (timedelta(hours=2, minutes=5), "2 h 5 min ago"),
        (timedelta(days=3), "3 days ago"),
    ],
)
def test_ago(now: datetime, delta: timedelta, expected: str) -> None:
    assert ago(now - delta, now) == expected


def test_ago_never(now: datetime) -> None:
    assert ago(None, now) == "never"
