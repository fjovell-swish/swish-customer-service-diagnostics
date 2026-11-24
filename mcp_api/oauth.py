"""
Sign-in with Microsoft for MCP clients (Claude Code, Claude Desktop, claude.ai connectors).

Microsoft Entra ID can't be the MCP clients' OAuth server itself: it has no dynamic client
registration (RFC 7591) and rejects the `resource` parameter (RFC 8707) that MCP clients send.
So this app is their OAuth server, through the MCP SDK (registration, /authorize, /token,
/revoke, PKCE, metadata), and hands the sign-in itself to Microsoft:

1. The client sends the person to /authorize; `Provider.authorize` records the sign-in and sends
   them to Microsoft (an ordinary confidential client: one app registration, PKCE, a nonce).
2. Microsoft sends them back to CALLBACK_PATH; `finish_sign_in` reads who they are from the ID
   token, finds the app's user with that email (their roles are the app's, as the auth proxy last
   set them) and sends them back to the client with a one-time code.
3. The client exchanges the code at /token for an access token (1 h) and a refresh token
   (30 days), issued and checked here. Only their hashes are stored.

Personal tokens (mcp_api/models.py) are still accepted where an access token is.
"""

import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import Any

import anyio.to_thread
import httpx
import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.provider import AuthorizationCode
from mcp.server.auth.provider import AuthorizationParams
from mcp.server.auth.provider import AuthorizeError
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.provider import RefreshToken
from mcp.server.auth.provider import TokenError
from mcp.server.auth.provider import construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as TokenResponse
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.responses import RedirectResponse
from starlette.responses import Response

from config.roles import user_roles
from mcp_api.auth import closing_connections
from mcp_api.models import PREFIX as PERSONAL_TOKEN_PREFIX
from mcp_api.models import OAuthAuthorization
from mcp_api.models import OAuthClient
from mcp_api.models import OAuthToken
from mcp_api.models import PersonalToken
from mcp_api.models import digest

CALLBACK_PATH = "/oauth/microsoft/callback"
MICROSOFT_LOGIN = "https://login.microsoftonline.com"
MICROSOFT_SCOPES = "openid profile email"
PERSONAL_TOKEN_CLIENT = "personal-token"
SIGN_IN_LIFETIME = timedelta(minutes=10)
CODE_LIFETIME = timedelta(minutes=5)
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_LIFETIME = timedelta(days=30)
REQUEST_TIMEOUT_SECONDS = 10


class SignInError(Exception):
    """A callback this app can't finish: no such sign-in, or it expired."""


async def in_thread[T](fn: Callable[..., T], *args: Any) -> T:
    """Django's ORM is synchronous: run it in a worker thread, which closes its connections."""
    return await anyio.to_thread.run_sync(closing_connections(fn), *args)


def microsoft_enabled() -> bool:
    return bool(
        settings.MICROSOFT_TENANT_ID
        and settings.MICROSOFT_CLIENT_ID
        and settings.MICROSOFT_CLIENT_SECRET
    )


def microsoft_url(endpoint: str) -> str:
    return f"{MICROSOFT_LOGIN}/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/{endpoint}"


def callback_url() -> str:
    return settings.MCP_BASE_URL.rstrip("/") + CALLBACK_PATH


def resource_url() -> str:
    """/mcp's URL: the resource every token here is for (RFC 8707)."""
    return settings.MCP_BASE_URL.rstrip("/") + "/mcp"


def pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def timestamp(moment: datetime) -> int:
    return int(moment.timestamp())


# --- The sign-in --------------------------------------------------------------------------------


def start_sign_in(client_id: str, params: AuthorizationParams) -> str:
    """Record the sign-in and return Microsoft's authorization URL for it."""
    now = timezone.now()
    OAuthAuthorization.objects.filter(expires_at__lte=now).delete()
    verifier, challenge = pkce_pair()
    authorization = OAuthAuthorization.objects.create(
        state=secrets.token_urlsafe(32),
        client_id=client_id,
        params=params.model_dump(mode="json"),
        microsoft_code_verifier=verifier,
        nonce=secrets.token_urlsafe(32),
        expires_at=now + SIGN_IN_LIFETIME,
    )
    return construct_redirect_uri(
        microsoft_url("authorize"),
        client_id=settings.MICROSOFT_CLIENT_ID,
        response_type="code",
        redirect_uri=callback_url(),
        response_mode="query",
        scope=MICROSOFT_SCOPES,
        state=authorization.state,
        nonce=authorization.nonce,
        code_challenge=challenge,
        code_challenge_method="S256",
    )


def microsoft_claims(code: str, verifier: str, nonce: str) -> dict[str, Any]:
    """Exchange Microsoft's code for the person's ID token claims."""
    response = httpx.post(
        microsoft_url("token"),
        data={
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(),
            "code_verifier": verifier,
            "scope": MICROSOFT_SCOPES,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    # Straight from Microsoft's token endpoint over TLS, so the signature needn't be checked
    # (OpenID Connect Core 3.1.3.7); the issuer, audience, expiry and nonce still are.
    claims: dict[str, Any] = jwt.decode(
        response.json()["id_token"],
        options={
            "verify_signature": False,
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": True,
        },
        audience=settings.MICROSOFT_CLIENT_ID,
        issuer=f"{MICROSOFT_LOGIN}/{settings.MICROSOFT_TENANT_ID}/v2.0",
    )
    if claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("The ID token's nonce isn't this sign-in's.")
    return claims


def user_for(claims: dict[str, Any]) -> User | None:
    """The app's active user with a role whose username or email is the Microsoft account's."""
    names = {
        str(value).lower()
        for value in (claims.get("email"), claims.get("preferred_username"))
        if value
    }
    query = Q()
    for name in names:
        query |= Q(username__iexact=name) | Q(email__iexact=name)
    if not query:
        return None
    return next(
        (user for user in User.objects.filter(query, is_active=True) if user_roles(user)), None
    )


def finish_sign_in(state: str, code: str, error: str) -> str:
    """Back from Microsoft: where to send the person, with a code for the client or an error."""
    authorization = OAuthAuthorization.objects.filter(
        state=state, user__isnull=True, expires_at__gt=timezone.now()
    ).first()
    if authorization is None:
        raise SignInError("This sign-in expired or was already used: start it again.")
    params = AuthorizationParams.model_validate(authorization.params)
    redirect_uri = str(params.redirect_uri)
    if error or not code:
        authorization.delete()
        return construct_redirect_uri(
            redirect_uri,
            error="access_denied",
            error_description=f"Microsoft sign-in failed: {error or 'no code'}.",
            state=params.state,
        )
    claims = microsoft_claims(code, authorization.microsoft_code_verifier, authorization.nonce)
    user = user_for(claims)
    if user is None:
        authorization.delete()
        return construct_redirect_uri(
            redirect_uri,
            error="access_denied",
            error_description=(
                f"No diagnostics user with a role for {claims.get('preferred_username')}:"
                " sign in to the diagnostics app once first, or ask for the support or data"
                " role."
            ),
            state=params.state,
        )
    client_code = secrets.token_urlsafe(32)
    authorization.user = user
    authorization.code_hash = digest(client_code)
    authorization.expires_at = timezone.now() + CODE_LIFETIME
    authorization.save()
    return construct_redirect_uri(redirect_uri, code=client_code, state=params.state)


async def microsoft_callback(request: Request) -> Response:
    """CALLBACK_PATH: Microsoft sends the person back here."""
    try:
        url = await in_thread(
            finish_sign_in,
            request.query_params.get("state", ""),
            request.query_params.get("code", ""),
            request.query_params.get("error", ""),
        )
    except SignInError as error:
        # The person is in their browser: tell them rather than fail.
        return PlainTextResponse(str(error), status_code=400)
    return RedirectResponse(url, status_code=302)


# --- Codes and tokens ---------------------------------------------------------------------------


def load_code(client_id: str, code: str) -> AuthorizationCode | None:
    authorization = OAuthAuthorization.objects.filter(
        code_hash=digest(code), client_id=client_id, expires_at__gt=timezone.now()
    ).first()
    if authorization is None:
        return None
    params = AuthorizationParams.model_validate(authorization.params)
    return AuthorizationCode(
        code=code,
        scopes=params.scopes or [],
        expires_at=authorization.expires_at.timestamp(),
        client_id=client_id,
        code_challenge=params.code_challenge,
        redirect_uri=params.redirect_uri,
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource,
        subject=str(authorization.user_id),
    )


def issue(client_id: str, user_id: int, scopes: list[str], resource: str | None) -> TokenResponse:
    now = timezone.now()
    OAuthToken.objects.filter(user_id=user_id, expires_at__lte=now).delete()
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    for kind, value, lifetime in (
        (OAuthToken.Kind.ACCESS, access, ACCESS_LIFETIME),
        (OAuthToken.Kind.REFRESH, refresh, REFRESH_LIFETIME),
    ):
        OAuthToken.objects.create(
            kind=kind,
            token_hash=digest(value),
            client_id=client_id,
            user_id=user_id,
            scopes=scopes,
            resource=resource,
            expires_at=now + lifetime,
        )
    return TokenResponse(
        access_token=access,
        expires_in=int(ACCESS_LIFETIME.total_seconds()),
        scope=" ".join(scopes) or None,
        refresh_token=refresh,
    )


def exchange_code(code: AuthorizationCode) -> TokenResponse:
    # Once only: whoever deletes it gets the tokens.
    used, _ = OAuthAuthorization.objects.filter(code_hash=digest(code.code)).delete()
    if not used:
        raise TokenError("invalid_grant", "This code was already used.")
    # A client that names no resource gets a token for this one.
    return issue(
        code.client_id, int(code.subject or 0), code.scopes, code.resource or resource_url()
    )


def load_refresh(client_id: str, token: str) -> RefreshToken | None:
    refresh = OAuthToken.objects.filter(
        kind=OAuthToken.Kind.REFRESH,
        token_hash=digest(token),
        client_id=client_id,
        expires_at__gt=timezone.now(),
        user__is_active=True,
    ).first()
    if refresh is None:
        return None
    return RefreshToken(
        token=token,
        client_id=client_id,
        scopes=refresh.scopes,
        expires_at=timestamp(refresh.expires_at),
        resource=refresh.resource,
        subject=str(refresh.user_id),
    )


def exchange_refresh(token: RefreshToken, scopes: list[str]) -> TokenResponse:
    # Rotated: the refresh token works once.
    used, _ = OAuthToken.objects.filter(token_hash=digest(token.token)).delete()
    if not used:
        raise TokenError("invalid_grant", "This refresh token was already used.")
    return issue(token.client_id, int(token.subject or 0), scopes or token.scopes, token.resource)


def load_access(token: str) -> AccessToken | None:
    if token.startswith(PERSONAL_TOKEN_PREFIX):
        user = PersonalToken.authenticate(token)
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id=PERSONAL_TOKEN_CLIENT,
            scopes=[],
            resource=resource_url(),
            subject=str(user.pk),
        )
    access = OAuthToken.objects.filter(
        kind=OAuthToken.Kind.ACCESS,
        token_hash=digest(token),
        expires_at__gt=timezone.now(),
        user__is_active=True,
    ).first()
    if access is None:
        return None
    return AccessToken(
        token=token,
        client_id=access.client_id,
        scopes=access.scopes,
        expires_at=timestamp(access.expires_at),
        resource=access.resource,
        subject=str(access.user_id),
    )


def revoke(token: str, client_id: str, subject: str | None) -> None:
    # The SDK asks to revoke the access and refresh tokens together: the client's for that user.
    OAuthToken.objects.filter(client_id=client_id, user_id=int(subject or 0)).delete()


def get_client(client_id: str) -> OAuthClientInformationFull | None:
    client = OAuthClient.objects.filter(client_id=client_id).first()
    if not client:
        return None
    return OAuthClientInformationFull.model_validate(client.info)


def register_client(info: OAuthClientInformationFull) -> None:
    OAuthClient.objects.create(client_id=info.client_id, info=info.model_dump(mode="json"))


class Provider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """The MCP SDK's OAuth server, backed by the database and Microsoft's sign-in."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await in_thread(get_client, client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await in_thread(register_client, client_info)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if not microsoft_enabled():
            raise AuthorizeError(
                "temporarily_unavailable", "Sign-in with Microsoft isn't configured here."
            )
        return await in_thread(start_sign_in, client.client_id, params)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return await in_thread(load_code, client.client_id, authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> TokenResponse:
        return await in_thread(exchange_code, authorization_code)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return await in_thread(load_refresh, client.client_id, refresh_token)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> TokenResponse:
        return await in_thread(exchange_refresh, refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await in_thread(load_access, token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await in_thread(revoke, token.token, token.client_id, token.subject)
