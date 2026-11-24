"""
Claude's second opinion on a case: everything the app knows goes to Claude, which writes an
assessment, the steps support can take, and whether the case needs the tech team (with a draft
Jira ticket).

What is sent: the charger and its connectors, the last days' incidents, refused badges, sessions,
maintenance and firmware (as stored by api-ocpp), the checks' findings, the rep's answers and the
rule-based diagnosis. What is not: drivers' emails, the charger's SIM and network identifiers,
firmware signatures; badge numbers are masked to their last characters, everywhere.
"""

import json
import logging
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
from anthropic.types import ToolUseBlock
from django.conf import settings
from django.db.models import Model
from django.utils.timezone import localtime

from diagnostics.snapshot import Snapshot
from diagnostics.workflow import BADGE
from diagnostics.workflow import Situation
from diagnostics.workflow import asked
from diagnostics.workflow import diagnose
from diagnostics.workflow import lookback

log = logging.getLogger(__name__)

# Personal data and secrets that never help a diagnosis.
EXCLUDED_FIELDS = {
    "email",
    "iccid",
    "imsi",
    "ip_address",
    "search_vector",
    "signature",
    "signing_certificate",
}
# Badge numbers (RFID UIDs, eMAIDs): kept apart by their last characters, never sent whole.
TOKEN_FIELDS = {"id_tag", "id_token", "parent_id_tag", "token_uid", "user_id_token", "vehicle_id_tag"}
TOKEN_VISIBLE_CHARS = 4
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 90
TOOL_NAME = "record_assessment"

SYSTEM_PROMPT = """\
You help Swish's customer support with "the charger doesn't work" cases. Swish runs an EV charging
platform: chargers speak OCPP 1.6 to central-system, which stores everything in api-ocpp (the data
you get); api-gateway serves the apps; api-gireve handles roaming (other eMSPs' cards and apps).

You get one case as JSON: the charger as api-ocpp stores it, its connectors, the recent incidents
(connections, disconnections), refused badges, sessions, maintenance and firmware updates; the
findings of automatic checks; the support rep's questions and answers; and the diagnosis that the
app's rules wrote. The rules are simple and pick the first explanation that fits: confirm it,
refine it or contradict it using the raw data. Badge numbers are masked ("...1234").

Support reps can: talk to the customer and to the site's owner or installer, look at the back
office, and send the usual remote commands (soft or hard reset, unlock connector, remote stop,
change availability, trigger a status notification). They can't change the platform's code or
configuration, the chargers' firmware or the hardware.

Be concrete and brief, and only claim what the data shows: cite timestamps, statuses, error codes
and stop reasons. Say what is missing when the data can't tell. Set needs_escalation when support
can't solve the case themselves (a platform bug, data that looks wrong or inconsistent, a
hardware fault that needs a technician, a roaming problem), and write the ticket for the Central
System team. Write in English.
"""

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessment": {
            "type": "string",
            "description": "What is going on, in a few sentences, citing the evidence.",
        },
        "likely_cause": {"type": "string", "description": "The likely cause, in one line."},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "agrees_with_rules": {
            "type": "boolean",
            "description": "Whether the rule-based diagnosis is right.",
        },
        "support_steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What support should do now, in order. Empty if nothing.",
        },
        "customer_reply": {
            "type": "string",
            "description": "A short, plain message support can send to the customer.",
        },
        "needs_escalation": {
            "type": "boolean",
            "description": "True when support can't solve it and the tech team must step in.",
        },
        "ticket_title": {
            "type": "string",
            "description": "A Jira title for the tech team: the charger and the problem.",
        },
        "ticket_description": {
            "type": "string",
            "description": (
                "The Jira description for the tech team, plain text: what happens, the evidence"
                " with timestamps, what support already tried, what to investigate."
            ),
        },
    },
    "required": [
        "assessment",
        "likely_cause",
        "confidence",
        "agrees_with_rules",
        "support_steps",
        "customer_reply",
        "needs_escalation",
        "ticket_title",
        "ticket_description",
    ],
}


@dataclass
class Assessment:
    assessment: str
    likely_cause: str
    confidence: str
    agrees_with_rules: bool
    support_steps: list[str]
    customer_reply: str
    needs_escalation: bool
    ticket_title: str
    ticket_description: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def mask(token: str) -> str:
    return "..." + token[-TOKEN_VISIBLE_CHARS:]


def row(instance: Model) -> dict[str, Any]:
    """A model instance's columns, without the excluded ones, badge numbers masked."""
    values: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        if field.name in EXCLUDED_FIELDS:
            continue
        value = getattr(instance, field.attname)
        if field.name in TOKEN_FIELDS and value:
            value = mask(str(value))
        values[field.name] = value
    return values


def tokens(snapshot: Snapshot, answers: dict[str, str]) -> set[str]:
    """Every badge number in the case, to mask wherever it shows up (answers, rule texts)."""
    found = {answers.get(BADGE, "").strip()}
    for instance in [*snapshot.rejected_rfids, *snapshot.transactions]:
        found.update(
            str(getattr(instance, name) or "")
            for name in TOKEN_FIELDS
            if hasattr(instance, name)
        )
    # Shorter than the visible part, masking would reveal it all anyway.
    return {token for token in found if len(token) > TOKEN_VISIBLE_CHARS}


def case_context(situation: Situation) -> str:
    """The case as JSON, as Claude gets it."""
    snapshot = situation.snapshot
    diagnosis = diagnose(situation)
    context = {
        "checked_at": localtime(situation.now),
        "looking_back_days": lookback(situation.answers).days or 1,
        "tenant": snapshot.tenant,
        "charger": row(snapshot.charge_point),
        "connectors": [row(connector) for connector in snapshot.connectors],
        "customer_connector": situation.connector.index if situation.connector else None,
        "incidents": [row(incident) for incident in snapshot.incidents],
        "refused_badges": [row(rejection) for rejection in snapshot.rejected_rfids],
        "sessions": [row(transaction) for transaction in snapshot.transactions],
        "maintenance": [row(maintenance) for maintenance in snapshot.maintenances],
        "firmware": [row(firmware) for firmware in snapshot.firmwares],
        "findings": [
            {
                "severity": finding.severity.label,
                "title": finding.title,
                "evidence": finding.evidence,
                "action": finding.action,
            }
            for finding in situation.findings
        ],
        "questions_and_answers": [
            {"question": question, "answer": answer} for question, answer in asked(situation)
        ],
        "rule_based_diagnosis": {
            "likely_cause": diagnosis.likely_cause,
            "confidence": diagnosis.confidence.label,
            "because": diagnosis.because,
            "next_steps": diagnosis.actions,
        },
    }
    text = json.dumps(context, indent=1, default=str)
    for token in tokens(snapshot, situation.answers):
        text = text.replace(token, mask(token))
    return text


def make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)


def assess(situation: Situation, client: anthropic.Anthropic | None = None) -> Assessment:
    client = client or make_client()
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "name": TOOL_NAME,
                "description": "Record the assessment of the case.",
                "input_schema": ASSESSMENT_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": case_context(situation)}],
    )
    log.info(
        "Assessed %s: %s input tokens, %s output tokens",
        situation.snapshot.charge_point.identity,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    # tool_choice forces exactly this tool, so the block is always there.
    block = next(block for block in response.content if isinstance(block, ToolUseBlock))
    values: dict[str, Any] = dict(block.input)
    return Assessment(**{name: values[name] for name in ASSESSMENT_SCHEMA["required"]})
