"""The MCP API: personal tokens, the /mcp endpoint, and its tools."""

from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
import time_machine
from django.contrib.auth.models import User
from django.db.models import Model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from config.asgi import build
from config.roles import DATA
from config.roles import SUPPORT
from config.roles import set_roles
from deployments.status import EnvironmentStatus
from diagnostics.models import Case
from mcp_api import auth
from mcp_api import server
from mcp_api.auth import closing_connections
from mcp_api.models import LIFETIME
from mcp_api.models import PersonalToken
from services.ocpp.models import ChargePointV16

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PROTOCOL = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL,
    "io.modelcontextprotocol/clientCapabilities": {},
}

# The tools as plain functions: without closing_connections, which would close the test's own
# connection (it's tested on its own below).
find_chargers = server.find_chargers_tool.__wrapped__  # type: ignore[attr-defined]
diagnose_charger = server.diagnose_charger.__wrapped__  # type: ignore[attr-defined]
list_cases = server.list_cases.__wrapped__  # type: ignore[attr-defined]
get_case = server.get_case.__wrapped__  # type: ignore[attr-defined]
get_deployments = server.get_deployments.__wrapped__  # type: ignore[attr-defined]


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    def factory(*roles: str, username: str = "ana@swish.example") -> User:
        user = User.objects.create_user(username, is_staff=True)
        set_roles(user, set(roles))
        return user

    return factory


@pytest.fixture
def make_ctx() -> Callable[..., Any]:
    """A tool's Context, as the endpoint builds it: the request's scope holds the user."""

    def factory(user: User | None) -> Any:
        scope = {}
        if user is not None:
            token = AccessToken(token="t", client_id="c", scopes=[], subject=str(user.pk))
            scope["user"] = AuthenticatedUser(token)
        return SimpleNamespace(
            request_context=SimpleNamespace(request=SimpleNamespace(scope=scope))
        )

    return factory


@pytest.fixture
def support_ctx(make_user: Callable[..., User], make_ctx: Callable[..., Any]) -> Any:
    return make_ctx(make_user(SUPPORT))


@pytest.fixture
def data_ctx(make_user: Callable[..., User], make_ctx: Callable[..., Any]) -> Any:
    return make_ctx(make_user(DATA, username="dan@swish.example"))


@pytest.fixture
def frozen(now: datetime) -> Iterator[None]:
    """The tools read the clock; the fixtures' records are dated from `now`."""
    with time_machine.travel(now, tick=False):
        yield


@pytest.fixture
def badge_charger(
    frozen: None,
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    make_connector: Callable[..., Model],
    make_rejection: Callable[..., Model],
    tenants: list[str],
) -> ChargePointV16:
    charge_point = save(tenants[0], make_charge_point(identity="CP-BADGE"))
    save(tenants[0], make_connector(charge_point=charge_point))
    save(tenants[0], make_rejection(identity="CP-BADGE", id_token="04A1B2C3D4"))
    return charge_point  # type: ignore[return-value]


@pytest.fixture
def mcp(db: None) -> Iterator[TestClient]:
    with TestClient(build()) as client:
        yield client


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": (params or {}) | {"_meta": META},
    }


def mcp_headers(token: str, method: str, name: str = "") -> dict[str, str]:
    headers = MCP_HEADERS | {"MCP-Protocol-Version": PROTOCOL, "Mcp-Method": method}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if name:
        headers["Mcp-Name"] = name
    return headers


# --- Tokens ---


def test_tokens_create_shows_the_value_once(make_user: Callable[..., User], now: datetime) -> None:
    token, value = PersonalToken.create(make_user(SUPPORT), "Claude Code", now)

    assert value.startswith("swd_") and value[:8] == token.key_start
    assert value not in token.key_hash
    assert token.expires_at == now + LIFETIME
    assert str(token) == f"Claude Code ({token.key_start}…)"


def test_tokens_authenticate(make_user: Callable[..., User]) -> None:
    user = make_user(SUPPORT)
    token, value = PersonalToken.create(user, "Claude Code", timezone.now())

    assert PersonalToken.authenticate(value) == user
    token.refresh_from_db()
    assert token.last_used_at is not None
    assert PersonalToken.authenticate(value + "x") is None


def test_tokens_expired_refused(make_user: Callable[..., User]) -> None:
    token, value = PersonalToken.create(
        make_user(SUPPORT), "old", timezone.now() - LIFETIME - timedelta(days=1)
    )

    assert token.expired
    assert PersonalToken.authenticate(value) is None


def test_tokens_inactive_user_refused(make_user: Callable[..., User]) -> None:
    user = make_user(SUPPORT)
    _, value = PersonalToken.create(user, "Claude Code", timezone.now())
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert PersonalToken.authenticate(value) is None


def test_tokens_page_lists_and_creates(make_client: Callable[..., Client]) -> None:
    client = make_client(SUPPORT)

    response = client.post(reverse("tokens"), {"action": "create", "name": "Laptop"})

    token = PersonalToken.objects.get()
    created = response.context["created"]
    assert token.name == "Laptop" and token.key_start == created[:8]
    assert f'--header "Authorization: Bearer {created}"'.encode() in response.content
    assert b"http://testserver/mcp" in response.content
    # Shown once: the next visit lists it without its value.
    listing = client.get(reverse("tokens"))
    assert created.encode() not in listing.content
    assert list(listing.context["tokens"]) == [token]


def test_tokens_page_default_name(make_client: Callable[..., Client]) -> None:
    make_client(DATA).post(reverse("tokens"), {"action": "create", "name": "  "})

    assert PersonalToken.objects.get().name == "MCP client"


def test_tokens_page_revokes_only_your_own(
    make_client: Callable[..., Client], make_user: Callable[..., User], now: datetime
) -> None:
    client = make_client(SUPPORT)
    client.post(reverse("tokens"), {"action": "create", "name": "mine"})
    mine = PersonalToken.objects.get()
    theirs, _ = PersonalToken.create(make_user(SUPPORT, username="bo@swish.example"), "x", now)

    response = client.post(reverse("tokens"), {"action": "revoke", "token": mine.pk})
    client.post(reverse("tokens"), {"action": "revoke", "token": theirs.pk})

    assert response.status_code == HTTPStatus.FOUND
    assert list(PersonalToken.objects.all()) == [theirs]


def test_tokens_page_needs_a_role(make_client: Callable[..., Client]) -> None:
    assert make_client().get(reverse("tokens")).status_code == HTTPStatus.FORBIDDEN


def test_tokens_linked_from_the_admin_home(make_client: Callable[..., Client]) -> None:
    content = make_client(DATA).get(reverse("admin:index")).content

    assert f'href="{reverse("tokens")}"'.encode() in content


# --- The endpoint ---


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("token", ["", "swd_unknown"])
def test_endpoint_refuses_without_a_valid_token(mcp: TestClient, token: str) -> None:
    response = mcp.post("/mcp", json=rpc("tools/list"), headers=mcp_headers(token, "tools/list"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    # Where an MCP client finds how to sign in (RFC 9728).
    assert (
        'resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"'
        in (response.headers["WWW-Authenticate"])
    )


@pytest.mark.django_db(transaction=True)
def test_endpoint_lists_the_tools(mcp: TestClient, make_user: Callable[..., User]) -> None:
    _, value = PersonalToken.create(make_user(SUPPORT), "test", timezone.now())

    response = mcp.post("/mcp", json=rpc("tools/list"), headers=mcp_headers(value, "tools/list"))

    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {
        "find_chargers",
        "diagnose_charger",
        "list_cases",
        "get_case",
        "get_deployments",
    }
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools.values())


@pytest.mark.django_db(transaction=True)
def test_endpoint_calls_a_tool_as_the_token_user(
    mcp: TestClient, make_user: Callable[..., User]
) -> None:
    user = make_user(SUPPORT)
    Case.objects.create(identity="CP-1", tenant="public", created_by=user)
    _, value = PersonalToken.create(user, "test", timezone.now())
    call = rpc("tools/call", {"name": "list_cases", "arguments": {}})

    response = mcp.post("/mcp", json=call, headers=mcp_headers(value, "tools/call", "list_cases"))

    result = response.json()["result"]
    assert result["isError"] is False
    assert [case["identity"] for case in result["structuredContent"]["result"]] == ["CP-1"]


@pytest.mark.django_db(transaction=True)
def test_endpoint_tool_refuses_without_the_role(
    mcp: TestClient, make_user: Callable[..., User]
) -> None:
    _, value = PersonalToken.create(make_user(DATA), "test", timezone.now())
    call = rpc("tools/call", {"name": "list_cases", "arguments": {}})

    response = mcp.post("/mcp", json=call, headers=mcp_headers(value, "tools/call", "list_cases"))

    result = response.json()["result"]
    assert result["isError"] is True
    assert "support role" in result["content"][0]["text"]


@pytest.mark.django_db(transaction=True)
def test_endpoint_leaves_everything_else_to_django(mcp: TestClient) -> None:
    response = mcp.get("/healthz")

    assert response.status_code == HTTPStatus.OK


def test_endpoint_closes_the_worker_thread_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    monkeypatch.setattr(auth.connections, "close_all", lambda: closed.append(True))

    assert closing_connections(lambda: 42)() == 42
    with pytest.raises(ValueError):
        closing_connections(int)("not a number")
    assert closed == [True, True]


# --- Tools ---


@pytest.mark.django_db(databases="__all__")
def test_tools_need_a_user(make_ctx: Callable[..., Any]) -> None:
    with pytest.raises(ToolError, match="signed in or with a personal token"):
        find_chargers(make_ctx(None), query="CP")


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_find_chargers(support_ctx: Any, badge_charger: ChargePointV16) -> None:
    [match] = find_chargers(support_ctx, query="CP-BADGE")

    assert (match["identity"], match["tenant"], match["connected"]) == ("CP-BADGE", "public", True)


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_diagnose_asks_the_first_question(
    data_ctx: Any, badge_charger: ChargePointV16
) -> None:
    result = diagnose_charger(data_ctx, identity="CP-BADGE")

    assert result["charger"]["identity"] == "CP-BADGE"
    assert result["next_question"]["key"] == "when"
    assert {"value": "earlier", "label": "Before today"} in result["next_question"]["choices"]
    # Badge numbers are masked, as for Claude's assessment.
    assert result["refused_badges"][0]["id_token"] == "...C3D4"


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_diagnose_with_every_answer(support_ctx: Any, badge_charger: ChargePointV16) -> None:
    answers = {"when": "now", "symptom": "refused", "start": "badge", "badge": "04A1B2C3D4"}

    result = diagnose_charger(support_ctx, identity="CP-BADGE", tenant="public", answers=answers)

    assert result["next_question"] is None
    assert result["rule_based_diagnosis"]["likely_cause"].startswith(
        "The badge ...C3D4 is refused"
    )
    assert "04A1B2C3D4" not in str(result)


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_diagnose_unknown_charger(support_ctx: Any) -> None:
    with pytest.raises(ToolError, match="try find_chargers"):
        diagnose_charger(support_ctx, identity="NOPE")


@pytest.mark.django_db(databases="__all__")
def test_tools_diagnose_unknown_tenant(support_ctx: Any) -> None:
    with pytest.raises(ToolError, match="Unknown tenant 'mars'"):
        diagnose_charger(support_ctx, identity="CP-1", tenant="mars")


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_diagnose_charger_in_several_tenants(
    support_ctx: Any,
    save: Callable[[str, Model], Model],
    make_charge_point: Callable[..., ChargePointV16],
    tenants: list[str],
) -> None:
    for tenant in tenants:
        save(tenant, make_charge_point(identity="CP-TWICE"))

    with pytest.raises(ToolError, match="several tenants"):
        diagnose_charger(support_ctx, identity="CP-TWICE")


@pytest.mark.django_db
def test_tools_inactive_user_refused(
    make_user: Callable[..., User], make_ctx: Callable[..., Any]
) -> None:
    user = make_user(SUPPORT)
    ctx = make_ctx(user)
    User.objects.filter(pk=user.pk).update(is_active=False)

    with pytest.raises(ToolError, match="No user"):
        list_cases(ctx)


@pytest.mark.django_db
def test_tools_cases_need_the_support_role(data_ctx: Any) -> None:
    with pytest.raises(ToolError, match="Needs the support role"):
        list_cases(data_ctx)


@pytest.mark.django_db
def test_tools_list_cases_filters(support_ctx: Any) -> None:
    Case.objects.create(identity="CP-1", tenant="public", status=Case.Status.CLOSED)
    Case.objects.create(identity="CP-1", tenant="public")
    Case.objects.create(identity="CP-2", tenant="public")

    by_charger = list_cases(support_ctx, identity="CP-1")
    closed = list_cases(support_ctx, status="closed")
    latest = list_cases(support_ctx, limit=1)

    assert [case["identity"] for case in by_charger] == ["CP-1", "CP-1"]
    assert [case["status"] for case in closed] == ["closed"]
    assert [case["identity"] for case in latest] == ["CP-2"]


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_get_case_masks_every_badge(support_ctx: Any, badge_charger: ChargePointV16) -> None:
    # Refused badge unknown to the rep: the rule names the charger's refused badge.
    case = Case.objects.create(
        identity="CP-BADGE",
        tenant="public",
        answers={"badge": "BADGE-OF-THE-REP"},
        likely_cause="The badge 04A1B2C3D4 is refused (RFID_DOES_NOT_EXIST)",
        summary="Badge BADGE-OF-THE-REP; refused 04A1B2C3D4",
    )

    result = get_case(support_ctx, case_id=case.pk)

    assert "04A1B2C3D4" not in str(result) and "BADGE-OF-THE-REP" not in str(result)
    assert (
        result["diagnosis"]["likely_cause"] == "The badge ...C3D4 is refused (RFID_DOES_NOT_EXIST)"
    )
    assert result["answers"]["badge"] == "...-REP"
    assert result["assessment"] is None and result["jira_issue"] is None


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_get_case_for_a_charger_that_disappeared(support_ctx: Any) -> None:
    case = Case.objects.create(
        identity="GONE", tenant="public", answers={"badge": "BADGE-GONE-1"}, summary="BADGE-GONE-1"
    )

    result = get_case(support_ctx, case_id=case.pk)

    assert result["diagnosis"]["summary"] == "...NE-1"


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_tools_get_case_short_badge_left_alone(support_ctx: Any) -> None:
    case = Case.objects.create(identity="GONE", tenant="public", answers={"badge": "B42"})

    assert get_case(support_ctx, case_id=case.pk)["answers"]["badge"] == "B42"


@pytest.mark.django_db
def test_tools_get_case_not_found(support_ctx: Any) -> None:
    with pytest.raises(ToolError, match="No case #404"):
        get_case(support_ctx, case_id=404)


@pytest.mark.django_db
def test_tools_deployments_need_the_data_role(support_ctx: Any) -> None:
    with pytest.raises(ToolError, match="Needs the data role"):
        get_deployments(support_ctx)


@pytest.mark.django_db
def test_tools_get_deployments(
    data_ctx: Any,
    make_run: Callable[..., Any],
    make_rollout: Callable[..., Any],
    make_status: Callable[..., EnvironmentStatus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed = make_status(make_run(), [make_rollout()])
    never_built = make_status(None, [])
    monkeypatch.setattr(server, "get_statuses", lambda: [deployed, never_built])

    rows = get_deployments(data_ctx)

    assert rows[0]["service"] == deployed.service.name
    assert rows[0]["commit"] == "0123456"
    assert rows[1]["commit"] is None and rows[1]["deployed_at"] is None
