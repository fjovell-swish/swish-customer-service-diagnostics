"""
The two ways in, as roles:

    data      query the data: every service table (read-only), per tenant, and the deployments page
    support   customer service: the diagnostics workflow and the case history

A role is a Django group of the same name. Behind the auth proxy the groups follow the user
service's groups on every request (settings.AUTH_PROXY["ROLE_GROUPS"], config/auth_proxy.py);
locally they're given in the admin (`seed_fake_data` creates a user per role). Superusers have
every role.
"""

from collections.abc import Callable
from collections.abc import Iterable
from functools import wraps
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.http import HttpResponse

DATA = "data"
SUPPORT = "support"
ROLES = (DATA, SUPPORT)


def role_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = settings.AUTH_PROXY["ROLE_GROUPS"]
    return groups


def roles_for_groups(groups: Iterable[str]) -> set[str]:
    """The roles a user service's groups grant."""
    granted = set(groups)
    return {role for role, role_groups_ in role_groups().items() if granted & set(role_groups_)}


def user_roles(user: AbstractBaseUser | AnonymousUser) -> set[str]:
    if not user.is_active or not isinstance(user, User):
        return set()
    if user.is_superuser:
        return set(ROLES)
    # Asked several times per page (header, admin index, each model): read the groups once.
    cached: set[str] | None = getattr(user, "_roles", None)
    if cached is None:
        cached = set(user.groups.filter(name__in=ROLES).values_list("name", flat=True))
        user._roles = cached  # type: ignore[attr-defined]
    return cached


def has_role(user: AbstractBaseUser | AnonymousUser, role: str) -> bool:
    return role in user_roles(user)


def set_roles(user: User, roles: set[str]) -> None:
    """Make the user's role groups exactly `roles` (only writes when they differ)."""
    current = set(user.groups.filter(name__in=ROLES).values_list("name", flat=True))
    if current != roles:
        user.groups.remove(*Group.objects.filter(name__in=current - roles))
        user.groups.add(*(Group.objects.get_or_create(name=role)[0] for role in roles - current))
    user._roles = set(roles)  # type: ignore[attr-defined]


def role_required(
    role: str,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """For views already behind the admin's login: 403 without the role."""

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if not has_role(request.user, role):
                raise PermissionDenied(f"Needs the {role} role.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def any_role_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """For views behind the admin's staff login: 403 for a signed-in user with neither role.

    Anonymous users pass through, so the view's own login redirect still applies.
    """

    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and not user_roles(request.user):
            raise PermissionDenied("Needs the data or the support role.")
        return view(request, *args, **kwargs)

    return wrapped
