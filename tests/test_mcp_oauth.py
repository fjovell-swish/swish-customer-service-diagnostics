"""Sign-in with Microsoft for MCP clients: this app's OAuth server (mcp_api/oauth.py)."""

import base64
import hashlib
import secrets
from collections.abc import Callable
from collections.abc import Iterator
from datetime import timedelta
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
import jwt
import pytest
import respx
from django.contrib.auth.models import User
from django.utils import timezone
from mcp.server.auth.provider import AuthorizationParams
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull
from starlette.testclient import TestClient

from config.asgi import build
from config.roles import SUPPORT
from config.roles import set_roles
from diagnostics.models import Case
from mcp_api import oauth
from mcp_api.models import OAuthAuthorization
from mcp_api.models import OAuthClient
from mcp_api.models import OAuthToken
from mcp_api.models import PersonalToken
from mcp_api.models import digest

TENANT = "tenant-1"
CLIENT_ID = "ms-client"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
REDIRECT_URI = "http://localhost:9999/callback"
RESOURCE = "http://localhost:8000/mcp"


@pytest.fixture
def microsoft(settings: Any) -> Any:
    settings.MICROSOFT_TENANT_ID = TENANT
    settings.MICROSOFT_CLIENT_ID = CLIENT_ID
    settings.MICROSOFT_CLIENT_SECRET = "secret"
    return settings


@pytest.fixture
def ana(db: None) -> User:
    user = User.objects.create_user("ana@swish.example", is_staff=True)
    set_roles(user, {SUPPORT})
    return user


@pytest.fixture
def make_id_token() -> Callable[..., str]:
    """Microsoft's ID token for a sign-in (signed with anything: its signature isn't checked)."""

    def factory(nonce: str, **claims: Any) -> str:
        values: dict[str, Any] = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": CLIENT_ID,
            "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
            "nonce": nonce,
            "preferred_username": "Ana@Swish.example",
        }
        return jwt.encode(
            values | claims, "not-microsofts-key-only-for-these-tests", algorithm="HS256"
        )

    return factory


@pytest.fixture
def microsoft_token_endpoint(make_id_token: Callable[..., str]) -> Iterator[Callable[..., None]]:
    """Answer Microsoft's token endpoint with an ID token for a sign-in's nonce."""
    with respx.mock(assert_all_called=False) as mock:

        def answer(nonce: str, status: int = HTTPStatus.OK, **claims: Any) -> None:
            mock.post(TOKEN_URL).respond(status, json={"id_token": make_id_token(nonce, **claims)})

        yield answer


@pytest.fixture
def params() -> AuthorizationParams:
    return AuthorizationParams(
        state="client-state",
        scopes=None,
        code_challenge="challenge",
        redirect_uri=REDIRECT_URI,
        redirect_uri_provided_explicitly=True,
        resource=RESOURCE,
    )


@pytest.fixture
def started(microsoft: Any, params: AuthorizationParams) -> OAuthAuthorization:
    """A sign-in on its way to Microsoft."""
    oauth.start_sign_in("client-1", params)
    return OAuthAuthorization.objects.get()


@pytest.fixture
def signed_in(
    started: OAuthAuthorization, ana: User, microsoft_token_endpoint: Callable[..., None]
) -> str:
    """A sign-in back from Microsoft: the code given to the client."""
    microsoft_token_endpoint(started.nonce)
    url = oauth.finish_sign_in(started.state, "ms-code", "")
    return parse_qs(urlparse(url).query)["code"][0]


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


# --- The whole flow, as an MCP client sees it ---


@pytest.mark.django_db(transaction=True)
def test_flow_sign_in_and_call_a_tool(
    microsoft: Any, ana: User, microsoft_token_endpoint: Callable[..., None]
) -> None:
    Case.objects.create(identity="CP-1", tenant="public", created_by=ana)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    with TestClient(build(), follow_redirects=False) as client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        registered = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "Claude Code",
            },
        ).json()
        to_microsoft = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge.rstrip("="),
                "code_challenge_method": "S256",
                "state": "client-state",
                "resource": RESOURCE,
            },
        )
        state = query(to_microsoft.headers["location"])["state"]
        microsoft_token_endpoint(OAuthAuthorization.objects.get(state=state).nonce)
        back = client.get(oauth.CALLBACK_PATH, params={"code": "ms-code", "state": state})
        tokens = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": query(back.headers["location"])["code"],
                "redirect_uri": REDIRECT_URI,
                "client_id": registered["client_id"],
                "code_verifier": verifier,
                "resource": RESOURCE,
            },
        ).json()
        call = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_cases", "arguments": {}},
            },
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
        )
        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": registered["client_id"],
            },
        )
        # The MCP SDK's revocation endpoint wants the field even from public clients.
        revoked = client.post(
            "/revoke",
            data={
                "token": refreshed.json()["access_token"],
                "client_id": registered["client_id"],
                "client_secret": "",
            },
        )

    assert metadata["registration_endpoint"] == "http://localhost:8000/register"
    assert urlparse(to_microsoft.headers["location"]).netloc == "login.microsoftonline.com"
    assert query(back.headers["location"])["state"] == "client-state"
    cases = call.json()["result"]["structuredContent"]["result"]
    assert [case["identity"] for case in cases] == ["CP-1"]
    assert refreshed.status_code == HTTPStatus.OK
    assert revoked.status_code == HTTPStatus.OK
    assert not OAuthToken.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_flow_without_microsoft_configured(settings: Any) -> None:
    settings.MICROSOFT_CLIENT_SECRET = ""
    with TestClient(build(), follow_redirects=False) as client:
        client_id = client.post(
            "/register",
            json={"redirect_uris": [REDIRECT_URI], "token_endpoint_auth_method": "none"},
        ).json()["client_id"]
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": "c" * 43,
                "code_challenge_method": "S256",
            },
        )

    assert query(response.headers["location"])["error"] == "temporarily_unavailable"


@pytest.mark.django_db(transaction=True)
def test_flow_callback_for_an_unknown_sign_in() -> None:
    with TestClient(build()) as client:
        response = client.get(oauth.CALLBACK_PATH, params={"state": "nope", "code": "x"})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "start it again" in response.text


# --- Steps ---


def test_pkce_pair_challenge_is_the_verifiers_hash() -> None:
    verifier, challenge = oauth.pkce_pair()

    digest_ = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    assert challenge == digest_.rstrip("=")


@pytest.mark.django_db
def test_start_sign_in_sends_to_microsoft(started: OAuthAuthorization) -> None:
    url = oauth.start_sign_in("client-1", AuthorizationParams.model_validate(started.params))

    sent = query(url)
    assert url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize")
    assert sent["client_id"] == CLIENT_ID
    assert sent["redirect_uri"] == "http://localhost:8000/oauth/microsoft/callback"
    assert sent["code_challenge_method"] == "S256"
    assert {"state", "nonce", "code_challenge"} <= set(sent)


@pytest.mark.django_db
def test_start_sign_in_drops_expired_ones(started: OAuthAuthorization) -> None:
    OAuthAuthorization.objects.update(expires_at=timezone.now())

    oauth.start_sign_in("client-1", AuthorizationParams.model_validate(started.params))

    assert OAuthAuthorization.objects.count() == 1


@pytest.mark.django_db
def test_finish_sign_in_gives_the_client_a_code(signed_in: str, ana: User) -> None:
    authorization = OAuthAuthorization.objects.get()

    assert authorization.user == ana
    assert authorization.code_hash == digest(signed_in)


@pytest.mark.django_db
def test_finish_sign_in_only_once(signed_in: str, started: OAuthAuthorization) -> None:
    with pytest.raises(oauth.SignInError):
        oauth.finish_sign_in(started.state, "ms-code", "")


@pytest.mark.django_db
def test_finish_sign_in_expired(started: OAuthAuthorization) -> None:
    OAuthAuthorization.objects.update(expires_at=timezone.now())

    with pytest.raises(oauth.SignInError):
        oauth.finish_sign_in(started.state, "ms-code", "")


@pytest.mark.django_db
def test_finish_sign_in_microsoft_refused(started: OAuthAuthorization) -> None:
    url = oauth.finish_sign_in(started.state, "", "access_denied")

    assert url.startswith(REDIRECT_URI)
    assert query(url)["error"] == "access_denied"
    assert query(url)["state"] == "client-state"
    assert not OAuthAuthorization.objects.exists()


@pytest.mark.django_db
def test_finish_sign_in_unknown_person(
    started: OAuthAuthorization, microsoft_token_endpoint: Callable[..., None]
) -> None:
    microsoft_token_endpoint(started.nonce, preferred_username="bo@swish.example")

    url = oauth.finish_sign_in(started.state, "ms-code", "")

    assert query(url)["error"] == "access_denied"
    assert "bo@swish.example" in query(url)["error_description"]


@pytest.mark.django_db
def test_microsoft_claims_checked(
    started: OAuthAuthorization, microsoft_token_endpoint: Callable[..., None]
) -> None:
    microsoft_token_endpoint("another-sign-ins-nonce")
    with pytest.raises(jwt.InvalidTokenError, match="nonce"):
        oauth.microsoft_claims("ms-code", started.microsoft_code_verifier, started.nonce)

    microsoft_token_endpoint(started.nonce, aud="another-app")
    with pytest.raises(jwt.InvalidAudienceError):
        oauth.microsoft_claims("ms-code", started.microsoft_code_verifier, started.nonce)

    microsoft_token_endpoint(started.nonce, status=HTTPStatus.BAD_REQUEST)
    with pytest.raises(httpx.HTTPStatusError):
        oauth.microsoft_claims("ms-code", started.microsoft_code_verifier, started.nonce)


@pytest.mark.django_db
def test_user_for_by_username_or_email(ana: User) -> None:
    bo = User.objects.create_user("bo", email="Bo@Swish.example")
    set_roles(bo, {SUPPORT})

    assert oauth.user_for({"preferred_username": "ANA@swish.example"}) == ana
    assert oauth.user_for({"email": "bo@swish.example"}) == bo
    assert oauth.user_for({}) is None


@pytest.mark.django_db
def test_user_for_needs_a_role(ana: User) -> None:
    set_roles(ana, set())

    assert oauth.user_for({"email": "ana@swish.example"}) is None


@pytest.mark.django_db
def test_codes_load_and_exchange_once(signed_in: str, ana: User) -> None:
    code = oauth.load_code("client-1", signed_in)

    assert code is not None and code.subject == str(ana.pk) and code.resource == RESOURCE
    assert oauth.load_code("another-client", signed_in) is None
    tokens = oauth.exchange_code(code)
    assert tokens.access_token and tokens.refresh_token
    with pytest.raises(TokenError):
        oauth.exchange_code(code)


@pytest.mark.django_db
def test_codes_expire(signed_in: str) -> None:
    OAuthAuthorization.objects.update(expires_at=timezone.now())

    assert oauth.load_code("client-1", signed_in) is None


@pytest.mark.django_db
def test_codes_without_a_resource_get_this_ones(signed_in: str) -> None:
    code = oauth.load_code("client-1", signed_in)
    assert code is not None

    tokens = oauth.exchange_code(code.model_copy(update={"resource": None}))

    access = oauth.load_access(tokens.access_token)
    assert access is not None and access.resource == RESOURCE


@pytest.mark.django_db
def test_tokens_access(ana: User) -> None:
    tokens = oauth.issue("client-1", ana.pk, ["read"], RESOURCE)

    access = oauth.load_access(tokens.access_token)
    assert access is not None
    assert (access.client_id, access.subject, access.scopes) == ("client-1", str(ana.pk), ["read"])
    assert oauth.load_access(tokens.refresh_token or "") is None
    OAuthToken.objects.update(expires_at=timezone.now())
    assert oauth.load_access(tokens.access_token) is None


@pytest.mark.django_db
def test_tokens_inactive_user_refused(ana: User) -> None:
    tokens = oauth.issue("client-1", ana.pk, [], RESOURCE)
    User.objects.filter(pk=ana.pk).update(is_active=False)

    assert oauth.load_access(tokens.access_token) is None
    assert oauth.load_refresh("client-1", tokens.refresh_token or "") is None


@pytest.mark.django_db
def test_tokens_personal_tokens_accepted(ana: User) -> None:
    _, value = PersonalToken.create(ana, "script", timezone.now())

    access = oauth.load_access(value)

    assert access is not None
    assert (access.client_id, access.subject) == (oauth.PERSONAL_TOKEN_CLIENT, str(ana.pk))
    assert access.resource == RESOURCE
    assert oauth.load_access(value + "x") is None


@pytest.mark.django_db
def test_tokens_refresh_rotates(ana: User) -> None:
    tokens = oauth.issue("client-1", ana.pk, ["read"], RESOURCE)
    refresh = oauth.load_refresh("client-1", tokens.refresh_token or "")
    assert refresh is not None
    assert oauth.load_refresh("another-client", tokens.refresh_token or "") is None

    renewed = oauth.exchange_refresh(refresh, [])

    assert renewed.scope == "read"
    assert oauth.load_refresh("client-1", tokens.refresh_token or "") is None
    with pytest.raises(TokenError):
        oauth.exchange_refresh(refresh, [])


@pytest.mark.django_db
def test_tokens_issue_drops_expired_ones(ana: User) -> None:
    oauth.issue("client-1", ana.pk, [], RESOURCE)
    OAuthToken.objects.update(expires_at=timezone.now())

    oauth.issue("client-1", ana.pk, [], RESOURCE)

    assert OAuthToken.objects.count() == 2


@pytest.mark.django_db
def test_tokens_revoke_the_clients_for_that_user(ana: User) -> None:
    tokens = oauth.issue("client-1", ana.pk, [], RESOURCE)
    oauth.issue("client-2", ana.pk, [], RESOURCE)

    oauth.revoke(tokens.access_token, "client-1", str(ana.pk))

    assert set(OAuthToken.objects.values_list("client_id", flat=True)) == {"client-2"}


@pytest.mark.django_db
def test_clients_register_and_get() -> None:
    info = OAuthClientInformationFull(client_id="client-1", redirect_uris=[REDIRECT_URI])

    oauth.register_client(info)

    assert oauth.get_client("client-1") == info
    assert str(OAuthClient.objects.get()) == "client-1"
    oauth.register_client(info.model_copy(update={"client_id": "c2", "client_name": "Claude"}))
    assert str(OAuthClient.objects.get(client_id="c2")) == "Claude"
    assert oauth.get_client("nope") is None
