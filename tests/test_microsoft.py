"""Sign-in with Microsoft (config/microsoft.py): the OpenID Connect flow and roles from groups."""

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
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config import microsoft
from config.roles import DATA
from config.roles import SUPPORT
from config.roles import user_roles

pytestmark = pytest.mark.django_db

TENANT = "tenant-1"
CLIENT_ID = "app-1"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"


@pytest.fixture(autouse=True)
def configured(settings: Any, role_groups: dict[str, str]) -> Any:
    settings.MICROSOFT_SIGN_IN = {
        **settings.MICROSOFT_SIGN_IN,
        "TENANT_ID": TENANT,
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": "secret",
    }
    return settings


@pytest.fixture
def make_id_token() -> Callable[..., str]:
    """Microsoft's ID token (signed with anything: its signature isn't checked)."""

    def factory(nonce: str, **claims: Any) -> str:
        values: dict[str, Any] = {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": CLIENT_ID,
            "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
            "nonce": nonce,
            "preferred_username": "Ana@Swish.example",
            "email": "ana@swish.example",
            "groups": ["group-support", "group-other"],
        }
        return jwt.encode(values | claims, "not-microsofts-key-only-for-these-tests", "HS256")

    return factory


@pytest.fixture
def token_endpoint(make_id_token: Callable[..., str]) -> Iterator[Callable[..., respx.Route]]:
    """Answer Microsoft's token endpoint with an ID token for a sign-in's nonce."""
    with respx.mock(assert_all_called=False) as mock:

        def answer(nonce: str, status: int = HTTPStatus.OK, **claims: Any) -> respx.Route:
            body = {"id_token": make_id_token(nonce, **claims)}
            # Named: a second answer in one test replaces the first.
            return mock.post(TOKEN_URL, name="token").respond(status, json=body)

        yield answer


@pytest.fixture
def started() -> Callable[..., tuple[Client, dict[str, str]]]:
    """A browser on its way to Microsoft, and what it was sent there with."""

    def factory(next_url: str = "") -> tuple[Client, dict[str, str]]:
        client = Client()
        response = client.get(reverse("microsoft-sign-in"), {"next": next_url})
        sent = {
            key: values[0]
            for key, values in parse_qs(urlparse(response["Location"]).query).items()
        }
        return client, sent

    return factory


@pytest.fixture
def sign_in(
    started: Callable[..., tuple[Client, dict[str, str]]],
    token_endpoint: Callable[..., respx.Route],
) -> Callable[..., tuple[Client, Any]]:
    """The whole round trip, with these ID token claims; the browser and the callback's answer."""

    def factory(next_url: str = "", **claims: Any) -> tuple[Client, Any]:
        client, sent = started(next_url)
        token_endpoint(sent["nonce"], **claims)
        response = client.get(
            reverse("microsoft-callback"), {"code": "ms-code", "state": sent["state"]}
        )
        return client, response

    return factory


def messages_of(client: Client) -> str:
    return client.get(reverse("admin:login")).content.decode()


# --- The round trip ---


def test_sign_in_sends_to_microsoft(started: Callable[..., tuple[Client, dict[str, str]]]) -> None:
    _, sent = started()

    assert sent["client_id"] == CLIENT_ID
    assert sent["redirect_uri"] == "http://testserver/accounts/microsoft/callback/"
    assert sent["scope"] == "openid profile email"
    assert sent["code_challenge_method"] == "S256"
    assert {"state", "nonce", "code_challenge"} <= set(sent)


def test_sign_in_creates_a_staff_user_with_the_groups_roles(
    sign_in: Callable[..., tuple[Client, Any]],
) -> None:
    client, response = sign_in()

    assert response["Location"] == reverse("start")
    user = User.objects.get()
    assert (user.username, user.email, user.is_staff) == (
        "ana@swish.example",
        "ana@swish.example",
        True,
    )
    assert not user.has_usable_password()
    assert user_roles(user) == {SUPPORT}
    assert client.get(reverse("start")).status_code == HTTPStatus.OK


def test_sign_in_existing_user_gets_the_groups_roles_again(
    make_client: Callable[..., Client], sign_in: Callable[..., tuple[Client, Any]]
) -> None:
    make_client(SUPPORT, username="ana@swish.example")

    sign_in(groups=["group-data"])

    assert user_roles(User.objects.get()) == {DATA}


def test_sign_in_goes_back_where_it_was_asked(
    sign_in: Callable[..., tuple[Client, Any]],
) -> None:
    _, back = sign_in(next_url="/guide/")
    _, elsewhere = sign_in(next_url="https://evil.example/")

    assert back["Location"] == "/guide/"
    assert elsewhere["Location"] == reverse("start")


def test_sign_in_token_endpoint_sent_the_code_and_verifier(
    started: Callable[..., tuple[Client, dict[str, str]]],
    token_endpoint: Callable[..., respx.Route],
) -> None:
    client, sent = started()
    route = token_endpoint(sent["nonce"])

    client.get(reverse("microsoft-callback"), {"code": "ms-code", "state": sent["state"]})

    form = parse_qs(route.calls.last.request.content.decode())
    assert form["code"] == ["ms-code"]
    assert form["client_secret"] == ["secret"]
    assert form["code_verifier"][0]


# --- Refusals ---


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"groups": ["group-other"]}, "isn&#x27;t in a group that gives access"),
        ({"preferred_username": "", "email": ""}, "didn&#x27;t say who you are"),
    ],
)
def test_refused_without_a_role_or_a_name(
    sign_in: Callable[..., tuple[Client, Any]], claims: dict[str, Any], message: str
) -> None:
    client, response = sign_in(**claims)

    assert response["Location"] == reverse("admin:login")
    assert "_auth_user_id" not in client.session
    assert message in messages_of(client)


def test_refused_group_overage(make_id_token: Callable[..., str]) -> None:
    values = jwt.decode(
        make_id_token("n", _claim_names={"groups": "src1"}),
        options={"verify_signature": False},
    )
    del values["groups"]

    with pytest.raises(microsoft.SignInError, match="too many groups"):
        microsoft.user_for(values)


def test_refused_deactivated_user(sign_in: Callable[..., tuple[Client, Any]]) -> None:
    User.objects.create_user("ana@swish.example", is_active=False)

    client, response = sign_in()

    assert response["Location"] == reverse("admin:login")
    assert "deactivated" in messages_of(client)


def test_refused_unknown_or_replayed_state(
    started: Callable[..., tuple[Client, dict[str, str]]],
) -> None:
    client, sent = started()

    wrong = client.get(reverse("microsoft-callback"), {"code": "c", "state": "another"})
    replayed = client.get(reverse("microsoft-callback"), {"code": "c", "state": sent["state"]})

    assert wrong["Location"] == replayed["Location"] == reverse("admin:login")
    assert "expired" in messages_of(client)


def test_refused_by_microsoft(started: Callable[..., tuple[Client, dict[str, str]]]) -> None:
    client, sent = started()

    response = client.get(
        reverse("microsoft-callback"),
        {"error": "access_denied", "error_description": "no", "state": sent["state"]},
    )

    assert response["Location"] == reverse("admin:login")
    assert "didn&#x27;t sign you in" in messages_of(client)


def test_refused_token_not_for_this_sign_in(
    started: Callable[..., tuple[Client, dict[str, str]]],
    token_endpoint: Callable[..., respx.Route],
) -> None:
    client, sent = started()
    request = client.get("/").wsgi_request
    token_endpoint("another-sign-ins-nonce")

    with pytest.raises(jwt.InvalidTokenError, match="nonce"):
        microsoft.claims(request, "c", "verifier", sent["nonce"])
    token_endpoint(sent["nonce"], aud="another-app")
    with pytest.raises(jwt.InvalidAudienceError):
        microsoft.claims(request, "c", "verifier", sent["nonce"])
    token_endpoint(sent["nonce"], iss="https://login.microsoftonline.com/another/v2.0")
    with pytest.raises(jwt.InvalidIssuerError):
        microsoft.claims(request, "c", "verifier", sent["nonce"])
    token_endpoint(sent["nonce"], exp=int(timezone.now().timestamp()) - 60)
    with pytest.raises(jwt.ExpiredSignatureError):
        microsoft.claims(request, "c", "verifier", sent["nonce"])
    token_endpoint(sent["nonce"], status=HTTPStatus.BAD_REQUEST)
    with pytest.raises(httpx.HTTPStatusError):
        microsoft.claims(request, "c", "verifier", sent["nonce"])


# --- Not set up ---


def test_not_set_up_no_button_and_no_sign_in(settings: Any) -> None:
    settings.MICROSOFT_SIGN_IN = {**settings.MICROSOFT_SIGN_IN, "CLIENT_SECRET": ""}
    client = Client()

    response = client.get(reverse("microsoft-sign-in"))

    assert response["Location"] == reverse("admin:login")
    page = messages_of(client)
    assert "isn&#x27;t set up here" in page
    assert "Sign in with Microsoft</a>" not in page


def test_login_page_offers_microsoft_first() -> None:
    page = Client().get(reverse("admin:login"), {"next": "/guide/"}).content.decode()

    assert f'href="{reverse("microsoft-sign-in")}?next=/guide/"' in page
    assert "Sign in with a password (administrators)" in page
