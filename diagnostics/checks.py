# Checks behind "the charger doesn't work".
#
# Each check reads a Snapshot and returns findings: what the backend sees, what support or ops
# should do, and a plain sentence support can send to the customer. Checks are ordered roughly
# by how often they explain a complaint: offline first, then faults, then authorisation and
# sessions.
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from enum import IntEnum
from uuid import UUID

from diagnostics.snapshot import Snapshot
from services.ocpp.models import ConnectorV16
from services.ocpp.models import TransactionV16

# central-system asks chargers for a heartbeat every CS_HEARTBEAT_INTERVAL (10 s by default), and
# some models are polled by central-system itself; several minutes of silence means a dead socket.
HEARTBEAT_STALE_AFTER = timedelta(minutes=5)
FLAPPING_DISCONNECTS = 5
PREPARING_STUCK_AFTER = timedelta(minutes=15)
PENDING_TRANSACTION_STUCK_AFTER = timedelta(minutes=10)
ONGOING_TRANSACTION_STUCK_AFTER = timedelta(hours=24)
# energy_delivered is in Wh; below this a session effectively delivered nothing.
NO_ENERGY_WH = 100
FAILED_FIRMWARE_STATUSES = {
    "download_failed",
    "installation_failed",
    "install_verification_failed",
    "invalid_signature",
}
IN_PROGRESS_FIRMWARE_STATUSES = {
    "downloading",
    "downloaded",
    "installing",
    "install_rebooting",
    "install_scheduled",
}


class Severity(IntEnum):
    OK = 0
    INFO = 1
    WARNING = 2
    PROBLEM = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Finding:
    severity: Severity
    title: str
    evidence: str
    action: str = ""
    customer_reply: str = ""


# OCPP 1.6 StatusNotification error codes, as stored by api-ocpp.
ERROR_CODE_ADVICE: dict[str, tuple[str, str]] = {
    "connector_lock_failure": (
        "The connector lock failed. Try a remote unlock; if it repeats, send a technician to"
        " check the lock.",
        "The charger can't lock the cable. Please unplug and plug the cable in firmly; we're also"
        " checking it remotely.",
    ),
    "ev_communication_error": (
        "The charger can't talk to the car (control pilot). Usually the cable, the car or a dirty"
        " socket.",
        "The charger can't communicate with your car. Please unplug, check the plug is clean and"
        " fully inserted, and try again. If it keeps happening with this car only, the car or"
        " cable may be the cause.",
    ),
    "ground_failure": (
        "Earth/residual-current fault. Needs an electrician on site; don't reset repeatedly.",
        "The charger detected an electrical safety fault and stopped itself. We're sending a"
        " technician; please don't use it until then.",
    ),
    "high_temperature": (
        "Over-temperature. Usually clears once cooled down; recurring means ventilation or"
        " hardware issue.",
        "The charger stopped because it got too hot. It should be usable again shortly; we're"
        " monitoring it.",
    ),
    "internal_error": (
        "Charger internal error. Try a soft reset, then a hard reset; escalate to the"
        " manufacturer if it persists.",
        "The charger reported an internal error. We're restarting it remotely; please try again"
        " in about 5 minutes.",
    ),
    "local_list_conflict": (
        "Local authorisation list conflict. Resend the local list (SendLocalList) or clear the"
        " cache.",
        "There is a badge list issue on the charger. We're fixing it remotely; please try again"
        " in a few minutes.",
    ),
    "over_current_failure": (
        "Over-current. Check the car's draw and the installation; recurring needs a technician.",
        "The charger stopped because the current was too high. Please try again; if it repeats"
        " we'll send a technician.",
    ),
    "over_voltage": (
        "Grid over-voltage. Installation / grid side problem, needs an electrician.",
        "The charger detected a problem with the electrical supply. We're sending a technician.",
    ),
    "power_meter_failure": (
        "Energy meter failure. Sessions may not be billed correctly; needs a technician.",
        "The charger's energy meter has a fault. We're sending a technician.",
    ),
    "power_switch_failure": (
        "Contactor / power switch failure. Needs a technician.",
        "The charger has a hardware fault and can't deliver power. We're sending a technician.",
    ),
    "reader_failure": (
        "RFID reader failure. Badges won't work; starting from the app may still work.",
        "The badge reader on this charger is faulty. Please start your session from the app while"
        " we repair it.",
    ),
    "reset_failure": (
        "The charger failed to reset. Try a hard reset; if it doesn't come back, a power cycle on"
        " site.",
        "The charger didn't restart properly. We're working on it remotely.",
    ),
    "under_voltage": (
        "Grid under-voltage. Check the supply and the site's load management.",
        "The charger isn't getting enough power from the electrical supply. We're investigating.",
    ),
    "weak_signal": (
        "Weak mobile/Wi-Fi signal. Expect disconnections; consider an antenna or another network.",
        "The charger has a weak network signal, which can interrupt sessions. We're looking into"
        " it.",
    ),
    "other_error": (
        "Vendor-specific error. Check the charger's info/vendor error code in its logs"
        " (GetDiagnostics).",
        "The charger reported an error. We're investigating and will come back to you.",
    ),
}

# RejectedRfid.reason_kind values written by api-ocpp's store_rejected_rfid.
REJECTION_ADVICE: dict[str, tuple[str, str]] = {
    "RFID_DOES_NOT_EXIST": (
        "Badge unknown to the platform. Check the badge id with the customer, or register it.",
        "Your badge isn't registered on this network. Please send us the number printed on it so"
        " we can check.",
    ),
    "RFID_NOT_ACCEPTED": (
        "Badge exists but is blocked, expired or invalid. Check its status in Rfids.",
        "Your badge is not active (blocked or expired). Please contact your badge provider or"
        " fleet manager.",
    ),
    "PAYMENT_REJECTED": (
        "Payment was refused for this badge/user.",
        "Your payment method was refused. Please check it in the app and try again.",
    ),
    "PRIVATE_CHARGER": (
        "Private charger: this badge isn't allowed on it.",
        "This charger is private and your badge isn't authorised on it. Please use a public"
        " charger or ask the site owner for access.",
    ),
    "EMSP_REJECTION": (
        "The customer's roaming provider (eMSP) refused the badge. Not a Swish-side problem.",
        "Your charging card provider refused the session. Please contact them, as the refusal"
        " came from their side.",
    ),
    "NO_AVAILABLE_CONNECTOR": (
        "No connector was available when the badge was presented.",
        "All connectors were busy or unavailable when you tried. Please try again on a free"
        " connector.",
    ),
    "DOUBLE_AUTH_VEHICLE_REQUIRED": (
        "Double authentication is on: the driver badge needs the vehicle badge too.",
        "This charger needs both your driver badge and your vehicle badge. Please present both.",
    ),
    "DOUBLE_AUTH_EXPIRED": (
        "Double authentication timed out between the two badges.",
        "The second badge wasn't presented in time. Please present both badges one right after"
        " the other.",
    ),
    "DOUBLE_AUTH_PAIR_REJECTED": (
        "The driver and vehicle badges aren't allowed together.",
        "This driver badge and vehicle badge aren't paired. Please contact your fleet manager.",
    ),
    "UNKNOWN": (
        "Badge rejected for an unrecorded reason. Check api-ocpp logs around that time.",
        "Your badge was refused. We're checking why and will come back to you.",
    ),
}


def ago(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "never"
    seconds = int((now - moment).total_seconds())
    if seconds < 0:
        # Clock skew between the charger, central-system and this server.
        return "just now"
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min ago"
    return f"{seconds // 86400} days ago"


def connector_label(connector: ConnectorV16) -> str:
    return f"Connector {connector.index}" if connector.index is not None else "Connector ?"


def check_registration(snapshot: Snapshot, now: datetime) -> list[Finding]:
    charge_point = snapshot.charge_point
    if charge_point.is_active:
        return []
    return [
        Finding(
            Severity.PROBLEM,
            "Charger not activated",
            "is_active is false, so BootNotification is answered Pending and the charger won't"
            " accept sessions.",
            "Activate the charger (is_active) in the back office once it's commissioned, then"
            " reset it.",
            "This charger hasn't been activated on our network yet. We're activating it now.",
        )
    ]


def check_connection(snapshot: Snapshot, now: datetime) -> list[Finding]:
    charge_point = snapshot.charge_point
    heartbeat = ago(charge_point.last_heartbeat, now)
    if not charge_point.connected:
        disconnected = next((i for i in snapshot.incidents if i.event == "disconnected"), None)
        since = f" since {ago(disconnected.started_at, now)}" if disconnected else ""
        return [
            Finding(
                Severity.PROBLEM,
                "Charger offline",
                f"Not connected to central-system{since}. Last heartbeat {heartbeat}.",
                "Check power and network on site (breaker, SIM/router; ICCID"
                f" {charge_point.iccid or 'unknown'}). Remote commands can't reach it until it"
                " reconnects.",
                "The charger has lost its connection to our network, so it can't start sessions."
                " Could you check that it has power (screen or lights on)? If it does, we'll look"
                " at its network connection.",
            )
        ]
    last_heartbeat = charge_point.last_heartbeat
    if last_heartbeat is None or now - last_heartbeat > HEARTBEAT_STALE_AFTER:
        return [
            Finding(
                Severity.PROBLEM,
                "Connected but silent",
                f"Marked connected, but last heartbeat {heartbeat}. The socket is probably dead on"
                " the charger side.",
                "Send a Reset (soft, then hard). If it doesn't answer, it needs a power cycle on"
                " site.",
                "The charger looks frozen on our side. We're restarting it remotely; please try"
                " again in about 5 minutes.",
            )
        ]
    return [Finding(Severity.OK, "Online", f"Connected, last heartbeat {heartbeat}.")]


def check_connection_stability(snapshot: Snapshot, now: datetime) -> list[Finding]:
    disconnects = sum(1 for incident in snapshot.incidents if incident.event == "disconnected")
    if disconnects < FLAPPING_DISCONNECTS:
        return []
    return [
        Finding(
            Severity.WARNING,
            "Unstable connection",
            f"{disconnects} disconnections in the last 24 h.",
            "Likely weak mobile signal or an unstable site network. Sessions can fail to start or"
            " stop while it's offline.",
            "The charger's connection to our network is unstable, which can stop sessions from"
            " starting. We're looking into it.",
        )
    ]


def check_availability(snapshot: Snapshot, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    if snapshot.charge_point.availability == "inoperative":
        findings.append(
            Finding(
                Severity.PROBLEM,
                "Charger set to inoperative",
                "The whole charger was made inoperative (ChangeAvailability), so it refuses"
                " sessions.",
                "If there's no planned maintenance, send ChangeAvailability operative.",
                "This charger was put out of service on our side. We're checking and will bring"
                " it back if possible.",
            )
        )
    for connector in snapshot.connectors:
        if connector.availability == "inoperative":
            findings.append(
                Finding(
                    Severity.PROBLEM,
                    f"{connector_label(connector)} set to inoperative",
                    "This connector was made inoperative (ChangeAvailability).",
                    "If there's no planned maintenance, send ChangeAvailability operative for"
                    " this connector.",
                    "This connector was put out of service on our side. Please use another"
                    " connector while we check.",
                )
            )
    return findings


def check_connectors(snapshot: Snapshot, now: datetime) -> list[Finding]:
    if not snapshot.connectors:
        return [
            Finding(
                Severity.WARNING,
                "No connectors known",
                "api-ocpp has no connector for this charger, so it hasn't sent any"
                " StatusNotification yet.",
                "Trigger a StatusNotification (TriggerMessage). If none arrives, check the"
                " charger's configuration.",
            )
        ]
    findings: list[Finding] = []
    for connector in snapshot.connectors:
        finding = connector_finding(connector, now)
        if finding:
            findings.append(finding)
    return findings


def connector_finding(connector: ConnectorV16, now: datetime) -> Finding | None:
    label = connector_label(connector)
    since = ago(connector.updated_at, now)
    if connector.status == "faulted":
        error_code = connector.error_code or "other_error"
        action, reply = ERROR_CODE_ADVICE.get(error_code, ERROR_CODE_ADVICE["other_error"])
        return Finding(
            Severity.PROBLEM,
            f"{label} faulted: {error_code}",
            f"Faulted, updated {since}.",
            action,
            reply,
        )
    if connector.error_code and connector.error_code != "no_error":
        action, reply = ERROR_CODE_ADVICE.get(
            connector.error_code, ERROR_CODE_ADVICE["other_error"]
        )
        return Finding(
            Severity.WARNING,
            f"{label} reports {connector.error_code}",
            f"Status {connector.status} with error code {connector.error_code}, updated {since}.",
            action,
            reply,
        )
    if connector.status == "unavailable":
        return Finding(
            Severity.PROBLEM,
            f"{label} unavailable",
            f"The charger reports this connector unavailable, updated {since}.",
            "Often a pending reset, maintenance or a reservation. Check availability and"
            " reservations; try a soft reset.",
            "This connector is currently unavailable. Please try another one while we check.",
        )
    if connector.status == "suspended_ev":
        return Finding(
            Severity.WARNING,
            f"{label}: the car isn't taking power",
            "Status suspended_ev since"
            f" {ago(connector.last_suspended_ev or connector.updated_at, now)}.",
            "The car is refusing energy: battery full, a charging schedule or charge limit in the"
            " car, or a car-side fault. Not a charger problem.",
            "The charger is ready, but your car isn't accepting power. Please check your car's"
            " charging settings (scheduled charging, charge limit) or whether the battery is"
            " already full.",
        )
    if connector.status == "suspended_evse":
        return Finding(
            Severity.WARNING,
            f"{label}: the charger is holding back power",
            f"Status suspended_evse, updated {since}.",
            "A charging profile or the site's load management is limiting power to 0. Check"
            " charging profiles on this connector and the site's power limits.",
            "Charging is paused by the site's power management. It should resume automatically"
            " when power is available.",
        )
    if (
        connector.status == "preparing"
        and connector.updated_at
        and now - connector.updated_at > PREPARING_STUCK_AFTER
    ):
        return Finding(
            Severity.WARNING,
            f"{label} stuck in preparing",
            "Cable plugged in (preparing) for"
            f" {ago(connector.updated_at, now).removesuffix(' ago')} without a session.",
            "Nobody authorised a session, or the authorisation didn't reach the charger. Check"
            " rejected badges below, or start it remotely.",
            "Your cable is plugged in but no session was started. Please badge or start the"
            " session from the app.",
        )
    return None


def check_rejected_badges(snapshot: Snapshot, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rejection in snapshot.rejected_rfids:
        key = (rejection.id_token, rejection.reason_kind)
        if key in seen:
            continue
        seen.add(key)
        count = sum(
            1 for other in snapshot.rejected_rfids if (other.id_token, other.reason_kind) == key
        )
        action, reply = REJECTION_ADVICE.get(rejection.reason_kind, REJECTION_ADVICE["UNKNOWN"])
        detail = f" ({rejection.reason})" if rejection.reason else ""
        findings.append(
            Finding(
                Severity.WARNING,
                f"Badge {rejection.id_token} refused: {rejection.reason_kind}",
                f"Refused {count}×, last {ago(rejection.created_at, now)}{detail}.",
                action,
                reply,
            )
        )
    return findings


def check_transactions(snapshot: Snapshot, now: datetime) -> list[Finding]:
    # A transaction's connector is nullable in api-ocpp, hence the optional key.
    connectors: dict[UUID | None, ConnectorV16] = {
        connector.id: connector for connector in snapshot.connectors
    }
    findings: list[Finding] = []
    for transaction in snapshot.transactions:
        finding = transaction_finding(transaction, connectors.get(transaction.connector_id), now)
        if finding:
            findings.append(finding)
    return findings


def transaction_finding(
    transaction: TransactionV16, connector: ConnectorV16 | None, now: datetime
) -> Finding | None:
    where = connector_label(connector) if connector else "Unknown connector"
    started = transaction.started_at or transaction.created_at
    title_prefix = f"Session #{transaction.id} on {where}"
    if (
        transaction.status == "PENDING"
        and started
        and now - started > PENDING_TRANSACTION_STUCK_AFTER
    ):
        return Finding(
            Severity.WARNING,
            f"{title_prefix} started but no energy",
            f"Started {ago(started, now)} (badge {transaction.id_tag}) and still PENDING: no meter"
            " values received.",
            "The charger accepted the start but never reported energy. Check the connector status"
            " (car suspended?) and MeterValues configuration; stop it remotely if the customer"
            " has left.",
            "Your session started but no energy has been delivered so far. Please check your car"
            " is accepting charge.",
        )
    if (
        transaction.status == "ONGOING"
        and started
        and now - started > ONGOING_TRANSACTION_STUCK_AFTER
    ):
        return Finding(
            Severity.PROBLEM,
            f"{title_prefix} still open after {ago(started, now).removesuffix(' ago')}",
            f"Badge {transaction.id_tag}. A session this old is almost certainly stuck and may"
            " block the connector.",
            "The StopTransaction was probably lost. Send RemoteStopTransaction; if the charger is"
            " idle, close the session in the back office and check the billed energy.",
            "A previous session on this connector was never closed. We're closing it so you can"
            " charge.",
        )
    if transaction.status == "FAILED":
        return Finding(
            Severity.WARNING,
            f"{title_prefix} failed",
            f"Created {ago(transaction.created_at, now)}, badge {transaction.id_tag}, provider"
            f" {transaction.provider or 'unknown'}.",
            "Check the job and the api-ocpp/central-system logs around that time.",
            "Your last session attempt failed on our side. Please try again; we're looking into"
            " the cause.",
        )
    if transaction.status == "FINISHED" and (transaction.energy_delivered or 0) < NO_ENERGY_WH:
        reason = transaction.reason or "unknown"
        return Finding(
            Severity.WARNING,
            f"{title_prefix} ended with no energy",
            f"Ended {ago(transaction.ended_at, now)}, stop reason {reason},"
            f" {transaction.energy_delivered or 0:.0f} Wh delivered, badge {transaction.id_tag}.",
            stop_reason_action(reason),
            "Your session ended without delivering energy. "
            + (
                "It was stopped because the cable was unplugged."
                if reason == "ev_disconnected"
                else "Please try again; if it happens again we'll investigate further."
            ),
        )
    return None


def stop_reason_action(reason: str) -> str:
    if reason == "ev_disconnected":
        return (
            "The car was unplugged right away; often the car refused to charge or the plug wasn't"
            " seated."
        )
    if reason in {"power_loss", "reboot", "hard_reset", "soft_reset"}:
        return (
            "The charger restarted or lost power during the session. Check for repeated reboots"
            " or supply issues."
        )
    if reason == "emergency_stop":
        return "Emergency stop button pressed. Check on site that it's been released."
    if reason == "de_authorized":
        return (
            "The charger stopped it after authorisation was revoked. Check the badge and any eMSP"
            " rejection."
        )
    return "Check the charger logs (GetDiagnostics) around the session time."


def check_maintenance(snapshot: Snapshot, now: datetime) -> list[Finding]:
    return [
        Finding(
            Severity.INFO,
            "Maintenance recorded",
            f"{maintenance.maintenance_at:%Y-%m-%d %H:%M} by"
            f" {maintenance.maintainer or 'unknown'}: {maintenance.reason or 'no reason given'}.",
            "Confirm with the maintainer whether the charger was left in service.",
        )
        for maintenance in snapshot.maintenances
    ]


def check_firmware(snapshot: Snapshot, now: datetime) -> list[Finding]:
    if not snapshot.firmwares:
        return []
    firmware = snapshot.firmwares[0]
    if firmware.status in FAILED_FIRMWARE_STATUSES:
        error = f": {firmware.error}" if firmware.error else ""
        return [
            Finding(
                Severity.WARNING,
                f"Last firmware update {firmware.status}",
                f"Update to {firmware.firmware_version or '?'}"
                f" {ago(firmware.updated_at, now)}{error}.",
                "The charger may be on an unexpected firmware. Check the reported version and"
                " retry the update.",
            )
        ]
    if firmware.status in IN_PROGRESS_FIRMWARE_STATUSES:
        return [
            Finding(
                Severity.INFO,
                f"Firmware update in progress ({firmware.status})",
                f"Update to {firmware.firmware_version or '?'} started"
                f" {ago(firmware.created_at, now)}.",
                "The charger can be unavailable or reboot during the update.",
                "The charger is installing a software update. It should be back within the next"
                " few minutes.",
            )
        ]
    return []


CHECKS: list[Callable[[Snapshot, datetime], list[Finding]]] = [
    check_registration,
    check_connection,
    check_connection_stability,
    check_availability,
    check_connectors,
    check_rejected_badges,
    check_transactions,
    check_maintenance,
    check_firmware,
]


def run_checks(snapshot: Snapshot, now: datetime) -> list[Finding]:
    findings = [finding for check in CHECKS for finding in check(snapshot, now)]
    # Stable sort: worst first, keeping the CHECKS order within a severity.
    return sorted(findings, key=lambda finding: -finding.severity)


def verdict(findings: list[Finding]) -> tuple[Severity, str]:
    worst = max((finding.severity for finding in findings), default=Severity.OK)
    if worst == Severity.PROBLEM:
        return worst, "The backend sees a problem that explains the complaint."
    if worst == Severity.WARNING:
        return worst, "Something looks off; it may explain the complaint."
    return worst, (
        "The backend sees the charger healthy. Ask the customer which connector, when, how they"
        " started (badge or app) and what the charger's screen or lights showed."
    )
