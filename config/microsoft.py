"""
Sign-in with Microsoft (Entra ID), as for the rest of Swish's platform.

The admin's login page offers "Sign in with Microsoft" (`sign_in`): an OpenID Connect code flow,
with PKCE and a nonce, as a confidential client of the app registration in
settings.MICROSOFT_SIGN_IN. Back from Microsoft (`callback`):

* the person is the ID token's `preferred_username` (their UPN, usually their email), a Django
  user created on their first sign-in, as staff (the admin's login requires it), with no password;
* their roles come from the ID token's `groups` (config/roles.py): ROLE_GROUPS says which Entra
  groups (object IDs) grant `data` and `support`. Only people with a role get in, and their roles
  are set again at every sign-in, so a change in Entra applies at their next one (sessions last
  SESSION_COOKIE_AGE).

The ID token comes straight from Microsoft's token endpoint, over TLS, in exchange for the code
and the client secret, so its signature isn't checked (OpenID Connect Core 3.1.3.7); its issuer,
audience, expiry and nonce are.
"""

import base64
import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from django.conf import settings
from django.contrib import auth
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from config.roles import roles_for_groups
from config.roles import set_roles

log = logging.getLogger(__name__)

LOGIN = "https://login.microsoftonline.com"
SCOPES = "openid profile email"
SESSION_KEY = "microsoft_sign_in"
REQUEST_TIMEOUT_SECONDS = 10
# The password backend's session check also fits these users: active, the same user.
BACKEND = "django.contrib.auth.backends.ModelBackend"


class SignInError(Exception):
    """Something the person can't fix by retrying with the same account."""


def cfg() -> dict[str, Any]:
    return dict(settings.MICROSOFT_SIGN_IN)


def enabled() -> bool:
    return all(cfg()[key] for key in ("TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"))


def endpoint(name: str) -> str:
    return f"{LOGIN}/{cfg()['TENANT_ID']}/oauth2/v2.0/{name}"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    return verifier, challenge.rstrip("=")


def safe_next(request: HttpRequest, next_url: str) -> str:
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse("start")


def sign_in(request: HttpRequest) -> HttpResponse:
    """Off to Microsoft's sign-in page; back at `callback`."""
    if not enabled():
        messages.error(request, "Sign-in with Microsoft isn't set up here.")
        return HttpResponseRedirect(reverse("admin:login"))
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    request.session[SESSION_KEY] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "next": safe_next(request, request.GET.get("next", "")),
    }
    query = {
        "client_id": cfg()["CLIENT_ID"],
        "response_type": "code",
        "redirect_uri": request.build_absolute_uri(reverse("microsoft-callback")),
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return HttpResponseRedirect(f"{endpoint('authorize')}?{urlencode(query)}")


def claims(request: HttpRequest, code: str, verifier: str, nonce: str) -> dict[str, Any]:
    """The ID token's claims, for this sign-in's code."""
    response = httpx.post(
        endpoint("token"),
        data={
            "client_id": cfg()["CLIENT_ID"],
            "client_secret": cfg()["CLIENT_SECRET"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": request.build_absolute_uri(reverse("microsoft-callback")),
            "code_verifier": verifier,
            "scope": SCOPES,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    values: dict[str, Any] = jwt.decode(
        response.json()["id_token"],
        # Without the signature check pyjwt skips these too unless asked for each.
        options={
            "verify_signature": False,
            "verify_exp": True,
            "verify_iss": True,
            "verify_aud": True,
            "require": ["exp", "iss", "aud", "nonce"],
        },
        audience=cfg()["CLIENT_ID"],
        issuer=f"{LOGIN}/{cfg()['TENANT_ID']}/v2.0",
    )
    if not secrets.compare_digest(str(values["nonce"]), nonce):
        raise jwt.InvalidTokenError("The ID token's nonce isn't this sign-in's.")
    return values


def user_for(values: dict[str, Any]) -> User:
    """The signed-in person as a staff user with their roles, or SignInError."""
    username = str(values.get("preferred_username") or values.get("email") or "").lower()
    if not username:
        raise SignInError("Microsoft didn't say who you are.")
    if "groups" not in values and "groups" in values.get("_claim_names", {}):
        # Too many groups for the token: the app registration must send only its own.
        log.warning("sign-in refused for %s: group overage in the ID token", username)
        raise SignInError("Microsoft sent too many groups; ask to send only the app's groups.")
    roles = roles_for_groups(values.get("groups", []))
    if not roles:
        log.warning("sign-in refused for %s: no group grants a role", username)
        raise SignInError(f"{username} isn't in a group that gives access to this app.")
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        user = User(username=username)
        user.set_unusable_password()
    if not user.is_active:
        raise SignInError(f"{username} is deactivated here.")
    user.email = str(values.get("email") or user.email)
    user.is_staff = True
    user.save()
    set_roles(user, roles)
    return user


def callback(request: HttpRequest) -> HttpResponse:
    """Back from Microsoft: sign the person in, or back to the login page saying why not."""
    started: dict[str, str] | None = request.session.pop(SESSION_KEY, None)
    state = request.GET.get("state", "")
    if not started or not secrets.compare_digest(started["state"], state):
        messages.error(request, "That sign-in expired or isn't this browser's; try again.")
        return HttpResponseRedirect(reverse("admin:login"))
    if "error" in request.GET:
        log.info("Microsoft refused a sign-in: %s", request.GET.get("error_description", ""))
        messages.error(request, "Microsoft didn't sign you in.")
        return HttpResponseRedirect(reverse("admin:login"))
    try:
        values = claims(
            request, request.GET.get("code", ""), started["verifier"], started["nonce"]
        )
        user = user_for(values)
    except SignInError as error:
        messages.error(request, str(error))
        return HttpResponseRedirect(reverse("admin:login"))
    auth.login(request, user, backend=BACKEND)
    return HttpResponseRedirect(started["next"])
