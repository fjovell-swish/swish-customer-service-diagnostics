"""
The MCP API: the diagnostics app's read-only tools for MCP clients (Claude Code, Claude Desktop),
at /mcp (config/asgi.py). Clients sign in with Microsoft through this app's OAuth server
(mcp_api/oauth.py), or send a personal token (mcp_api/models.py).

The tools reuse the app's own code, so a client gets what support sees: the charger search, the
snapshot and checks, the workflow's questions and diagnosis, the cases and the deployments. Like
Claude's assessment (diagnostics/assistant.py), they leave drivers' emails, the chargers' SIM and
IP, and firmware signatures out, and mask badge numbers everywhere: tool results go to a model.

Roles as in the app: the charger tools need `support` or `data`, the cases `support`, the
deployments `data`.
"""

import json
from typing import Annotated
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.auth.settings import RevocationOptions
from mcp.server.mcpserver import Context
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from pydantic import Field

from config.roles import DATA
from config.roles import SUPPORT
from config.roles import has_role
from deployments.status import get_statuses
from diagnostics.assistant import TOKEN_VISIBLE_CHARS
from diagnostics.assistant import case_context
from diagnostics.assistant import masked
from diagnostics.assistant import tokens
from diagnostics.checks import run_checks
from diagnostics.models import Case
from diagnostics.snapshot import ChargerMatch
from diagnostics.snapshot import collect
from diagnostics.snapshot import find_chargers
from diagnostics.workflow import BADGE
from diagnostics.workflow import Situation
from diagnostics.workflow import lookback
from diagnostics.workflow import next_question
from mcp_api.auth import closing_connections
from mcp_api.oauth import CALLBACK_PATH
from mcp_api.oauth import Provider
from mcp_api.oauth import microsoft_callback

MCP_PATH = "/mcp"
MAX_CASES = 50
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

server = MCPServer(
    auth_server_provider=Provider(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(settings.MCP_BASE_URL),
        resource_server_url=AnyHttpUrl(settings.MCP_BASE_URL.rstrip("/") + MCP_PATH),
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
        # Refuse tokens issued for another server (RFC 8707).
        validate_token_resource=True,
    ),
    name="swish-diagnostics",
    title="Swish charger diagnostics",
    instructions=(
        "Read-only diagnostics of Swish's EV chargers, from the live api-ocpp data. Start with"
        " find_chargers, then diagnose_charger: it returns the charger, its recent events,"
        " the automatic checks and the rule-based diagnosis, and asks the next question that"
        " would change the diagnosis (answer it by calling again with `answers`). Support's"
        " cases are in list_cases and get_case; deployments in get_deployments. Badge numbers"
        " are masked."
    ),
)


server.custom_route(CALLBACK_PATH, methods=["GET"])(microsoft_callback)


def caller(ctx: Context, *roles: str) -> User:
    """The token's user, if they have one of these roles."""
    request = ctx.request_context.request
    authenticated = getattr(request, "scope", {}).get("user")
    access_token: AccessToken | None = getattr(authenticated, "access_token", None)
    subject = access_token and access_token.subject
    user = subject and User.objects.filter(pk=subject, is_active=True).first()
    if not user:
        raise ToolError("No user: call this through /mcp, signed in or with a personal token.")
    if not any(has_role(user, role) for role in roles):
        raise ToolError(f"Needs the {' or the '.join(roles)} role.")
    return user


def plain(value: Any) -> Any:
    """JSON types only: dates, uuids and decimals as Django's JSON encoder writes them."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def charger(identity: str, tenant: str | None) -> ChargerMatch:
    if tenant is not None and tenant not in settings.OCPP_TENANTS:
        raise ToolError(f"Unknown tenant {tenant!r}: one of {', '.join(settings.OCPP_TENANTS)}.")
    matches = [
        match
        for match in find_chargers(identity)
        if match.charge_point.identity == identity and tenant in (None, match.tenant)
    ]
    if not matches:
        raise ToolError(f"No charger with the identity {identity!r}: try find_chargers.")
    if len(matches) > 1:
        tenants = ", ".join(match.tenant for match in matches)
        raise ToolError(f"{identity!r} is in several tenants ({tenants}): pass `tenant`.")
    return matches[0]


@server.tool(name="find_chargers", annotations=READ_ONLY)
@closing_connections
def find_chargers_tool(
    ctx: Context,
    query: Annotated[str, Field(description="An identity, or part of a name or serial number.")],
) -> list[dict[str, Any]]:
    """Find chargers in every api-ocpp tenant: an exact identity, or else fragments."""
    caller(ctx, SUPPORT, DATA)
    return [
        plain(
            {
                "identity": match.charge_point.identity,
                "tenant": match.tenant,
                "name": match.charge_point.charger_name,
                "customer": match.charge_point.customer_name,
                "city": match.charge_point.city,
                "connected": match.charge_point.connected,
                "status": match.charge_point.status,
            }
        )
        for match in find_chargers(query)
    ]


@server.tool(annotations=READ_ONLY)
@closing_connections
def diagnose_charger(
    ctx: Context,
    identity: Annotated[str, Field(description="The charger's exact identity.")],
    tenant: Annotated[
        str | None, Field(description="Its api-ocpp tenant, if it's in several.")
    ] = None,
    answers: Annotated[
        dict[str, str] | None,
        Field(
            description="Answers so far, by question key (from `next_question`): the value of"
            " a choice, or free text. `when: earlier` looks back 7 days instead of 24 h."
        ),
    ] = None,
) -> dict[str, Any]:
    """One charger as support sees it: its data, the checks, and the diagnosis for the answers.

    `next_question` is the next question that could change the diagnosis (null when none is
    left): ask the customer, then call again with its answer added to `answers`.
    """
    caller(ctx, SUPPORT, DATA)
    match = charger(identity, tenant)
    answers = answers or {}
    now = timezone.now()
    snapshot = collect(match.tenant, match.charge_point, now, lookback(answers))
    situation = Situation(snapshot, run_checks(snapshot, now), answers, now)
    question = next_question(situation)
    result: dict[str, Any] = json.loads(case_context(situation))
    result["next_question"] = question and {
        "key": question.key,
        "text": question.text,
        "choices": [{"value": value, "label": label} for value, label in question.choices],
        "help": question.help,
    }
    return result


@server.tool(annotations=READ_ONLY)
@closing_connections
def list_cases(
    ctx: Context,
    identity: Annotated[str | None, Field(description="Only this charger's cases.")] = None,
    status: Annotated[str | None, Field(description="open, diagnosed or closed.")] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_CASES)] = 20,
) -> list[dict[str, Any]]:
    """Support's cases, newest first."""
    caller(ctx, SUPPORT)
    cases = Case.objects.select_related("created_by")
    if identity:
        cases = cases.filter(identity=identity)
    if status:
        cases = cases.filter(status=status)
    return [
        plain(
            {
                "id": case.pk,
                "identity": case.identity,
                "tenant": case.tenant,
                "status": case.status,
                "ticket": case.ticket,
                "jira_issue": case.jira_issue,
                "created_by": str(case.created_by or ""),
                "created_at": case.created_at,
            }
        )
        for case in cases[:limit]
    ]


@server.tool(annotations=READ_ONLY)
@closing_connections
def get_case(ctx: Context, case_id: int) -> dict[str, Any]:
    """One case: the answers, the diagnosis as written, Claude's assessment and the Jira issue."""
    caller(ctx, SUPPORT)
    case = Case.objects.select_related("created_by").filter(pk=case_id).first()
    if case is None:
        raise ToolError(f"No case #{case_id}.")
    # The diagnosis and summary can name any badge refused on the charger: mask those too.
    match = next((m for m in find_chargers(case.identity) if m.tenant == case.tenant), None)
    if match is None:
        badge = case.answers.get(BADGE, "").strip()
        badges = {badge} if len(badge) > TOKEN_VISIBLE_CHARS else set()
    else:
        snapshot = collect(case.tenant, match.charge_point, timezone.now(), lookback(case.answers))
        badges = tokens(snapshot, case.answers)
    value = plain(
        {
            "id": case.pk,
            "identity": case.identity,
            "tenant": case.tenant,
            "status": case.status,
            "ticket": case.ticket,
            "created_by": str(case.created_by or ""),
            "created_at": case.created_at,
            "answers": case.answers,
            "diagnosis": {
                "likely_cause": case.likely_cause,
                "confidence": case.confidence,
                "customer_reply": case.customer_reply,
                "summary": case.summary,
                "diagnosed_at": case.diagnosed_at,
            },
            "assessment": case.assessment or None,
            "jira_issue": case.jira_issue_url or None,
        }
    )
    masked_value: dict[str, Any] = json.loads(masked(json.dumps(value), badges))
    return masked_value


@server.tool(annotations=READ_ONLY)
@closing_connections
def get_deployments(ctx: Context) -> list[dict[str, Any]]:
    """What each service runs in staging and production: CI's last run and the cluster's state."""
    caller(ctx, DATA)
    return [
        plain(
            {
                "service": status.service.name,
                "environment": status.environment.name,
                "health": status.health,
                "reason": status.reason,
                "commit": status.run and status.run.short_sha,
                "commit_message": status.run and status.run.commit_message,
                "deployed_at": status.run and status.run.run_started_at,
                "unreleased_commits": status.unreleased_commits,
            }
        )
        for status in get_statuses()
    ]
