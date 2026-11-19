"""
The guided "the charger doesn't work" workflow: which question to ask the support rep next, and
the diagnosis once nothing is missing.

Everything here is a pure function of a Snapshot (what api-ocpp knows), the checks' findings and
the rep's answers so far. Questions are asked only when they can change the diagnosis: a charger
with one connector never asks which connector, a refused badge question only comes after "badge".
The diagnosis is rules, in order: the first rule that explains the complaint wins, the others'
findings still go in the ticket summary.
"""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from enum import IntEnum

from django.utils.timezone import localtime

from diagnostics.checks import ERROR_CODE_ADVICE
from diagnostics.checks import NO_ENERGY_WH
from diagnostics.checks import ONGOING_TRANSACTION_STUCK_AFTER
from diagnostics.checks import REJECTION_ADVICE
from diagnostics.checks import Finding
from diagnostics.checks import Severity
from diagnostics.checks import connector_label
from diagnostics.checks import stop_reason_action
from diagnostics.checks import verdict
from diagnostics.snapshot import LOOKBACK
from diagnostics.snapshot import Snapshot
from services.ocpp.models import ConnectorV16
from services.ocpp.models import RejectedRfid
from services.ocpp.models import TransactionV16

Answers = dict[str, str]
UNKNOWN = "unknown"
YES = "yes"
NO = "no"
YES_NO: list[tuple[str, str]] = [(YES, "Yes"), (NO, "No"), (UNKNOWN, "Don't know")]

# "Before today" looks back a week instead of the usual 24 h.
EARLIER_LOOKBACK = timedelta(days=7)

WHEN = "when"
CONNECTOR = "connector"
SYMPTOM = "symptom"
POWER = "power"
START = "start"
BADGE = "badge"
BADGE_REACTION = "badge_reaction"
SCREEN = "screen"
OTHER_CHARGERS = "other_chargers"

WHEN_CHOICES = [
    ("now", "Right now, or in the last hour"),
    ("today", "Earlier today"),
    ("earlier", "Before today"),
]
SYMPTOM_CHOICES = [
    ("dead", "Nothing happens: the screen or lights are off"),
    ("refused", "The badge or the app is refused"),
    ("no_charge", "A session starts but the car doesn't charge"),
    ("stops", "Charging stops early"),
    ("cable_stuck", "The cable is stuck in the charger"),
    ("error", "The charger shows an error"),
    ("other", "Something else"),
]
START_CHOICES = [
    ("badge", "An RFID badge"),
    ("swish_app", "The Swish app"),
    ("other_app", "Another app or roaming card"),
    ("plug_and_charge", "Plug & Charge (just plugged in)"),
    (UNKNOWN, "Don't know"),
]


class Confidence(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    # Empty: a free-text answer (which may be left empty).
    choices: list[tuple[str, str]] = field(default_factory=list)
    help: str = ""


@dataclass
class Situation:
    """What a question or a rule can look at."""

    snapshot: Snapshot
    findings: list[Finding]
    answers: Answers
    now: datetime

    def answer(self, key: str) -> str:
        return self.answers.get(key, "")

    @property
    def connector(self) -> ConnectorV16 | None:
        """The connector the customer used: the only one, or the one the rep picked."""
        if len(self.snapshot.connectors) == 1:
            return self.snapshot.connectors[0]
        picked = self.answer(CONNECTOR)
        return next(
            (c for c in self.snapshot.connectors if str(c.index) == picked),
            None,
        )

    @property
    def badge(self) -> str:
        return self.answer(BADGE).strip()

    def badge_rejections(self) -> list[RejectedRfid]:
        """Refusals of the customer's badge, or of any badge when the number is unknown."""
        badge = self.badge.upper()
        return [
            rejection
            for rejection in self.snapshot.rejected_rfids
            if not badge or rejection.id_token.upper() == badge
        ]

    def transactions(self) -> list[TransactionV16]:
        """Sessions on the customer's connector (all connectors when it isn't known)."""
        connector = self.connector
        if connector is None:
            return list(self.snapshot.transactions)
        return [t for t in self.snapshot.transactions if t.connector_id == connector.id]

    def badge_transactions(self) -> list[TransactionV16]:
        badge = self.badge.upper()
        return [t for t in self.transactions() if badge and (t.id_tag or "").upper() == badge]


def lookback(answers: Answers) -> timedelta:
    return EARLIER_LOOKBACK if answers.get(WHEN) == "earlier" else LOOKBACK


def label(choices: list[tuple[str, str]], value: str) -> str:
    return dict(choices).get(value, value or "not given")


# --- Questions --------------------------------------------------------------------------------


def ask_when(situation: Situation) -> Question | None:
    return Question(
        WHEN,
        "When did it happen?",
        WHEN_CHOICES,
        "Before today, we look at the last 7 days instead of the last 24 h.",
    )


def ask_connector(situation: Situation) -> Question | None:
    connectors = situation.snapshot.connectors
    if len(connectors) < 2:
        return None
    choices = [(str(c.index), f"{connector_label(c)} (now {c.status})") for c in connectors]
    return Question(CONNECTOR, "Which connector was the customer using?", choices + [YES_NO[2]])


def ask_symptom(situation: Situation) -> Question | None:
    return Question(SYMPTOM, "What does the customer see?", SYMPTOM_CHOICES)


def ask_power(situation: Situation) -> Question | None:
    offline = not situation.snapshot.charge_point.connected
    if not offline and situation.answer(SYMPTOM) != "dead":
        return None
    return Question(
        POWER,
        "Does the charger have power (screen or lights on)?",
        YES_NO,
        "Tells a power cut on site apart from a network problem.",
    )


def ask_start(situation: Situation) -> Question | None:
    if situation.answer(SYMPTOM) not in {"refused", "no_charge", "stops", "other"}:
        return None
    return Question(START, "How did the customer try to start charging?", START_CHOICES)


def ask_badge(situation: Situation) -> Question | None:
    if situation.answer(START) != "badge":
        return None
    return Question(
        BADGE,
        "What's the number printed on the badge?",
        help="Leave empty if the customer doesn't know it.",
    )


def ask_badge_reaction(situation: Situation) -> Question | None:
    # Worth asking only when the backend never heard of the badge.
    if situation.answer(START) != "badge":
        return None
    if situation.badge_rejections() or situation.badge_transactions():
        return None
    return Question(
        BADGE_REACTION,
        "Did the charger react when the badge was presented (beep, light, message)?",
        YES_NO,
    )


def ask_screen(situation: Situation) -> Question | None:
    if situation.answer(SYMPTOM) != "error":
        return None
    return Question(
        SCREEN,
        "What does the charger's screen say (error code or message)?",
        help="Leave empty if the customer can't tell.",
    )


def ask_other_chargers(situation: Situation) -> Question | None:
    if situation.answer(SYMPTOM) not in {"no_charge", "stops"}:
        return None
    return Question(
        OTHER_CHARGERS,
        "Has this car charged fine on other chargers recently?",
        YES_NO,
        "Tells a car-side problem apart from a charger-side one.",
    )


QUESTIONS: list[Callable[[Situation], Question | None]] = [
    ask_when,
    ask_connector,
    ask_symptom,
    ask_power,
    ask_start,
    ask_badge,
    ask_badge_reaction,
    ask_screen,
    ask_other_chargers,
]
QUESTION_ORDER = [
    WHEN,
    CONNECTOR,
    SYMPTOM,
    POWER,
    START,
    BADGE,
    BADGE_REACTION,
    SCREEN,
    OTHER_CHARGERS,
]


def next_question(situation: Situation) -> Question | None:
    for ask in QUESTIONS:
        question = ask(situation)
        if question is not None and question.key not in situation.answers:
            return question
    return None


def without_last_answer(answers: Answers) -> Answers:
    """The answers minus the latest one in question order (the rep's "Back")."""
    answered = [key for key in QUESTION_ORDER if key in answers]
    if not answered:
        return dict(answers)
    return {key: value for key, value in answers.items() if key != answered[-1]}


def asked(situation: Situation) -> list[tuple[str, str]]:
    """The questions that were asked, with the answers, in order: for the page and the ticket."""
    pairs = []
    for ask in QUESTIONS:
        question = ask(situation)
        if question is None or question.key not in situation.answers:
            continue
        value = situation.answers[question.key]
        pairs.append(
            (question.text, label(question.choices, value) if question.choices else value or "—")
        )
    return pairs


# --- Diagnosis --------------------------------------------------------------------------------


@dataclass
class Diagnosis:
    likely_cause: str
    confidence: Confidence
    because: str
    actions: list[str]
    customer_reply: str
    summary: str = ""


Rule = Callable[[Situation], Diagnosis | None]


def rule_not_activated(situation: Situation) -> Diagnosis | None:
    if situation.snapshot.charge_point.is_active:
        return None
    return Diagnosis(
        "The charger isn't activated on the platform",
        Confidence.HIGH,
        "is_active is false: the charger's BootNotification is answered Pending.",
        ["Activate the charger in the back office once it's commissioned, then reset it."],
        "This charger hasn't been activated on our network yet. We're activating it now.",
    )


def rule_offline(situation: Situation) -> Diagnosis | None:
    charge_point = situation.snapshot.charge_point
    if charge_point.connected:
        return None
    power = situation.answer(POWER)
    if power == NO:
        return Diagnosis(
            "No power at the charger",
            Confidence.HIGH,
            "The charger is offline and the customer sees no screen or lights.",
            [
                "Ask the site to check the charger's breaker and residual-current device.",
                "If the supply is fine, send a technician.",
            ],
            "The charger seems to have no power. We're asking the site to check its electrical"
            " supply; please use another charger in the meantime.",
        )
    if power == YES:
        return Diagnosis(
            "The charger has power but no network connection",
            Confidence.HIGH,
            "The charger is offline although its screen or lights are on.",
            [
                f"Check the SIM (ICCID {charge_point.iccid or 'unknown'}) or the site's"
                " router / Wi-Fi.",
                "A power cycle on site often brings the modem back.",
            ],
            "The charger has lost its connection to our network, so it can't start sessions."
            " We're working on it; please use another charger in the meantime.",
        )
    return Diagnosis(
        "The charger is offline",
        Confidence.MEDIUM,
        "Not connected to central-system; we don't know whether it has power.",
        [
            "Find out whether it has power (site contact): no power means the supply, power means"
            " the network."
        ],
        "The charger has lost its connection to our network. Could you check whether its screen"
        " or lights are on? That tells us whether it's a power or a network problem.",
    )


def rule_charger_inoperative(situation: Situation) -> Diagnosis | None:
    connector = situation.connector
    if situation.snapshot.charge_point.availability == "inoperative":
        what = "The charger"
    elif connector is not None and connector.availability == "inoperative":
        what = connector_label(connector)
    else:
        return None
    return Diagnosis(
        f"{what} was set out of service",
        Confidence.HIGH,
        "Availability is inoperative (ChangeAvailability).",
        ["If no maintenance is planned, send ChangeAvailability operative."],
        "This charger was put out of service on our side. We're checking whether it can be"
        " brought back.",
    )


def rule_connector_faulted(situation: Situation) -> Diagnosis | None:
    connector = situation.connector
    if connector is None or connector.status != "faulted":
        return None
    error_code = connector.error_code or "other_error"
    action, reply = ERROR_CODE_ADVICE.get(error_code, ERROR_CODE_ADVICE["other_error"])
    return Diagnosis(
        f"{connector_label(connector)} is faulted ({error_code})",
        Confidence.HIGH,
        f"The charger reports {error_code} on the connector the customer used.",
        [action],
        reply,
    )


def rule_cable_stuck(situation: Situation) -> Diagnosis | None:
    if situation.answer(SYMPTOM) != "cable_stuck":
        return None
    open_sessions = [t for t in situation.transactions() if t.status in {"PENDING", "ONGOING"}]
    actions = ["Send UnlockConnector for the connector."]
    if open_sessions:
        actions.insert(0, "Stop the open session first (RemoteStopTransaction).")
    return Diagnosis(
        "The connector lock didn't release",
        Confidence.HIGH if open_sessions else Confidence.MEDIUM,
        (
            "A session is still open on the connector, so the charger keeps the cable locked."
            if open_sessions
            else "The customer reports the cable stuck; no open session is recorded."
        ),
        actions + ["If it stays locked, send a technician (lock actuator)."],
        "We're releasing the cable remotely; please try to unplug it again in a minute.",
    )


def rule_badge_refused(situation: Situation) -> Diagnosis | None:
    if situation.answer(START) not in {"badge", "other_app"}:
        return None
    rejections = situation.badge_rejections()
    if not rejections:
        return None
    latest = rejections[0]
    action, reply = REJECTION_ADVICE.get(latest.reason_kind, REJECTION_ADVICE["UNKNOWN"])
    return Diagnosis(
        f"The badge {latest.id_token} is refused ({latest.reason_kind})",
        Confidence.HIGH if situation.badge else Confidence.MEDIUM,
        f"{len(rejections)} refusal(s) recorded on this charger"
        + ("" if situation.badge else "; the badge number isn't known, so it may be another one")
        + ".",
        [action],
        reply,
    )


def rule_badge_not_heard(situation: Situation) -> Diagnosis | None:
    if situation.answer(START) != "badge" or situation.badge_transactions():
        return None
    reaction = situation.answer(BADGE_REACTION)
    if reaction == NO:
        return Diagnosis(
            "The charger doesn't read the badge",
            Confidence.MEDIUM,
            "Nothing reached the backend and the charger didn't react to the badge.",
            [
                "Try a known-good badge on site: if it fails too, the RFID reader is faulty.",
                "Otherwise the customer's badge is damaged or of an unsupported type.",
            ],
            "The charger doesn't seem to read your badge. Please start from the app for now; we're"
            " checking the badge reader.",
        )
    if reaction == YES:
        return Diagnosis(
            "The badge was read but the request never reached us",
            Confidence.MEDIUM,
            "The charger reacted to the badge but no authorisation or session is recorded.",
            [
                "Check the charger's connection around that time (disconnections in the"
                " findings).",
                "Check its local authorisation list / cache configuration.",
            ],
            "Your badge was read but the request didn't reach our system. We're checking the"
            " charger's connection; please try again in a few minutes.",
        )
    return None


def rule_remote_start_lost(situation: Situation) -> Diagnosis | None:
    # "A session starts but..." means the start did arrive: that's for the car rule below.
    if situation.answer(SYMPTOM) not in {"refused", "other"}:
        return None
    if situation.answer(START) not in {"swish_app", "other_app"}:
        return None
    if situation.transactions():
        return None
    return Diagnosis(
        "The start from the app never reached the charger",
        Confidence.MEDIUM,
        "No session was recorded on the connector in the period.",
        [
            "Check the remote start job in api-ocpp (jobs aren't linked to a charger, search by"
            ' time) and central-system\'s logs for "Charge point not found".',
            "If the customer used another operator's app, their eMSP may never have sent it.",
        ],
        "Your start request didn't reach the charger. Please try again; if it fails again, try"
        " with a badge or from another charger.",
    )


def rule_car_not_charging(situation: Situation) -> Diagnosis | None:
    if situation.answer(SYMPTOM) not in {"no_charge", "stops"}:
        return None
    connector = situation.connector
    if connector is not None and connector.status == "suspended_evse":
        return Diagnosis(
            "The charger is holding back power (charging profile or load management)",
            Confidence.HIGH,
            "The connector is suspended_evse: the charger, not the car, limits power to 0.",
            ["Check the connector's charging profiles and the site's power limits."],
            "Charging is paused by the site's power management. It should resume automatically"
            " when power is available.",
        )
    other_chargers = situation.answer(OTHER_CHARGERS)
    car_refuses = connector is not None and connector.status == "suspended_ev"
    no_energy = [
        t
        for t in situation.transactions()
        if t.status == "PENDING" or (t.energy_delivered or 0) < NO_ENERGY_WH
    ]
    if other_chargers == NO:
        return Diagnosis(
            "A problem on the car's side",
            Confidence.HIGH if car_refuses else Confidence.MEDIUM,
            "The car doesn't charge on other chargers either"
            + (", and it refuses power here (suspended_ev)." if car_refuses else "."),
            ["Nothing to fix on the charger. Suggest the customer contacts their car's dealer."],
            "The charger looks fine, but your car doesn't seem to accept charge, here or"
            " elsewhere. Please check its charging settings (schedule, charge limit) or contact"
            " your dealer.",
        )
    if car_refuses:
        return Diagnosis(
            "The car isn't taking power",
            Confidence.MEDIUM,
            "The connector is suspended_ev: the car refuses energy (battery full, schedule,"
            " charge limit).",
            ["Ask the customer to check the car's charging schedule and charge limit."],
            "The charger is ready, but your car isn't accepting power. Please check your car's"
            " charging settings (scheduled charging, charge limit) or whether the battery is"
            " already full.",
        )
    if situation.answer(SYMPTOM) == "stops":
        finished = [t for t in situation.transactions() if t.status == "FINISHED"]
        if finished:
            reason = finished[0].reason or "unknown"
            return Diagnosis(
                f"The last session was stopped ({reason})",
                Confidence.MEDIUM,
                f"Session #{finished[0].id} ended with stop reason {reason}.",
                [stop_reason_action(reason)],
                "Your session was stopped early. We're looking into why; please try again.",
            )
    if no_energy and other_chargers == YES:
        return Diagnosis(
            "The charger doesn't deliver energy to this car",
            Confidence.MEDIUM,
            "Sessions start but deliver no energy, while the car charges elsewhere.",
            [
                "Check the connector's meter values and charging profiles; try a soft reset.",
                "If it repeats with several cars, send a technician (contactor, power module).",
            ],
            "Your session started but the charger didn't deliver energy. We're restarting it"
            " remotely; please try again in about 5 minutes.",
        )
    return None


def rule_error_on_screen(situation: Situation) -> Diagnosis | None:
    if situation.answer(SYMPTOM) != "error":
        return None
    message = situation.answer(SCREEN).strip()
    return Diagnosis(
        "The charger shows an error" + (f": {message}" if message else ""),
        Confidence.LOW,
        "The backend has no matching fault; the error is only on the charger's screen.",
        [
            "Look the message up in the manufacturer's documentation.",
            "Pull the charger's logs (GetDiagnostics) and try a soft reset.",
        ],
        "Thanks for the details. We're checking the error with the charger's logs and will come"
        " back to you.",
    )


def rule_stuck_session(situation: Situation) -> Diagnosis | None:
    stuck = [
        t
        for t in situation.transactions()
        if t.status == "ONGOING"
        and t.started_at
        and situation.now - t.started_at > ONGOING_TRANSACTION_STUCK_AFTER
    ]
    if not stuck:
        return None
    return Diagnosis(
        "An old session is still open and blocks the connector",
        Confidence.MEDIUM,
        f"Session #{stuck[0].id} has been open since"
        f" {localtime(stuck[0].started_at):%Y-%m-%d %H:%M}.",
        [
            "Send RemoteStopTransaction; if the charger is idle, close the session in the back"
            " office and check the billed energy."
        ],
        "A previous session on this connector was never closed. We're closing it so you can"
        " charge.",
    )


def rule_worst_finding(situation: Situation) -> Diagnosis | None:
    problems = [f for f in situation.findings if f.severity >= Severity.WARNING]
    if not problems:
        return None
    finding = problems[0]
    return Diagnosis(
        finding.title,
        Confidence.MEDIUM if finding.severity == Severity.PROBLEM else Confidence.LOW,
        finding.evidence,
        [finding.action] if finding.action else [],
        finding.customer_reply
        or "We've found something unusual on the charger and are looking into it.",
    )


def rule_nothing_found(situation: Situation) -> Diagnosis:
    return Diagnosis(
        "No fault visible in the backend",
        Confidence.LOW,
        "The charger is online and no fault, refusal or failed session is recorded.",
        [
            "Ask the customer for a photo or video of the charger's screen while trying.",
            "Escalate to the Central System team with this summary.",
        ],
        "On our side the charger looks healthy. Could you send us a photo of its screen while"
        " you try to charge, and the time you tried? That will help us find the cause.",
    )


RULES: list[Rule] = [
    rule_not_activated,
    rule_offline,
    rule_charger_inoperative,
    rule_connector_faulted,
    rule_cable_stuck,
    rule_badge_refused,
    rule_badge_not_heard,
    rule_remote_start_lost,
    rule_car_not_charging,
    rule_stuck_session,
    rule_error_on_screen,
    rule_worst_finding,
]


def diagnose(situation: Situation) -> Diagnosis:
    diagnosis = next(
        (d for d in (rule(situation) for rule in RULES) if d is not None),
        None,
    ) or rule_nothing_found(situation)
    diagnosis.summary = summary(situation, diagnosis)
    return diagnosis


def summary(situation: Situation, diagnosis: Diagnosis) -> str:
    """Plain text for the support ticket."""
    charge_point = situation.snapshot.charge_point
    connector = situation.connector
    severity, overall = verdict(situation.findings)
    lines = [
        f"Charger: {charge_point.identity} ({charge_point.charger_name or 'no name'},"
        f" {charge_point.customer_name or 'no customer'}), tenant {situation.snapshot.tenant}",
        f"Connector: {connector_label(connector) if connector else 'not known'}",
        f"Checked: {localtime(situation.now):%Y-%m-%d %H:%M %Z}, looking back"
        f" {lookback(situation.answers).days or 1} day(s)",
        "",
        "Reported:",
        *(f"- {question} {answer}" for question, answer in asked(situation)),
        "",
        f"Backend ({severity.label}): {overall}",
        *(
            f"- [{finding.severity.label}] {finding.title}: {finding.evidence}"
            for finding in situation.findings
        ),
        "",
        f"Likely cause ({diagnosis.confidence.label} confidence): {diagnosis.likely_cause}",
        f"Because: {diagnosis.because}",
        "Next steps:",
        *(f"- {action}" for action in diagnosis.actions),
    ]
    return "\n".join(lines)
