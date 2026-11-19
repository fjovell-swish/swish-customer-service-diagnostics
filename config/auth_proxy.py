"""
Sign-in delegated to Swish's user service through an auth proxy, as for central-system-new-world's
read-only admin.

The app sits behind a proxy (oauth2-proxy, an API gateway, ...) that signs people in against the
user service and forwards, on every request,

    X-Forwarded-User:    the person's username or email
    X-Forwarded-Groups:  their groups, comma-separated
    X-Proxy-Secret:      a shared secret proving the request came through the proxy

(header names are settings.AUTH_PROXY). Django's RemoteUserBackend turns the user header into a
`django.contrib.auth` user, created on first visit; this module adds two checks:

* only members of AUTH_PROXY["ALLOWED_GROUPS"] get in, re-checked on every request, so removing
  someone from the group in the user service locks them out on their next click;
* the identity headers are ignored unless the proxy secret matches, so a request that reaches the
  container without going through the proxy cannot claim to be anyone.

Admitted users are staff, which is what the diagnostics page requires. No passwords are stored.
"""

import hmac
import logging
from typing import Any

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http.request import HttpHeaders

log = logging.getLogger(__name__)

BACKEND = "config.auth_proxy.GroupRemoteUserBackend"


def cfg() -> dict[str, Any]:
    return dict(settings.AUTH_PROXY)


def from_proxy(request: HttpRequest) -> bool:
    """True when the request carries the proxy's shared secret (or none is configured)."""
    secret = str(cfg()["PROXY_SECRET"])
    if not secret:
        return True
    sent = request.headers.get(str(cfg()["PROXY_SECRET_HEADER"]), "")
    return hmac.compare_digest(sent.encode(), secret.encode())


def groups(request: HttpRequest) -> set[str]:
    raw = request.headers.get(str(cfg()["GROUPS_HEADER"]), "")
    return {group.strip() for group in raw.split(",") if group.strip()}


def in_allowed_group(request: HttpRequest) -> bool:
    return bool(groups(request) & set(cfg()["ALLOWED_GROUPS"]))


class GroupRemoteUserBackend(RemoteUserBackend):
    """RemoteUserBackend that admits only members of the allowed groups, as staff."""

    create_unknown_user = True

    def authenticate(  # type: ignore[override]
        self, request: HttpRequest | None, remote_user: str | None
    ) -> User | None:
        if request is None or not remote_user:
            return None
        if not in_allowed_group(request):
            log.warning("sign-in refused for %s: not in %s", remote_user, cfg()["ALLOWED_GROUPS"])
            return None
        user = super().authenticate(request, remote_user)
        return user if isinstance(user, User) else None

    def configure_user(  # type: ignore[override]
        self, request: HttpRequest | None, user: User, created: bool = True
    ) -> User:
        if created:
            user.set_unusable_password()  # sign-in is the proxy's; there is no password here
        if created or not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff", "password"])
        return user


class ProxyHeaderMiddleware(RemoteUserMiddleware):
    """RemoteUserMiddleware reading the proxy's user header, and only when the proxy sent it."""

    header = HttpHeaders.to_wsgi_name(str(settings.AUTH_PROXY["USER_HEADER"]))  # at start-up

    def process_request(self, request: HttpRequest) -> None:
        if not from_proxy(request):
            request.META.pop(self.header, None)  # unproven identity: treat as no header at all
        super().process_request(request)
        signed_in_remotely = request.session.get(auth.BACKEND_SESSION_KEY) == BACKEND
        if request.user.is_authenticated and signed_in_remotely and not in_allowed_group(request):
            log.info("%s left the allowed groups; signing out", request.user.get_username())
            auth.logout(request)
