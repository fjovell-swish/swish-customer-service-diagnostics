"""The two ways in: `data` (query the data) and `support` (customer service), from Entra groups."""

from collections.abc import Callable
from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from config.roles import DATA
from config.roles import SUPPORT
from config.roles import has_role
from config.roles import roles_for_groups
from config.roles import set_roles
from config.roles import user_roles

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user("ana@swish.example", is_staff=True)


@pytest.fixture
def support_client(make_client: Callable[..., Client]) -> Client:
    return make_client(SUPPORT)


@pytest.fixture
def data_client(make_client: Callable[..., Client]) -> Client:
    return make_client(DATA)


@pytest.fixture
def case_url() -> str:
    return reverse("case", args=[1])


@pytest.mark.parametrize(
    ("groups", "roles"),
    [
        ({"support"}, {SUPPORT}),
        ({"data", "eng"}, {DATA}),
        ({"ops"}, {DATA, SUPPORT}),
        ({"eng"}, set()),
    ],
)
def test_roles_for_groups(role_groups: dict[str, str], groups: set[str], roles: set[str]) -> None:
    assert roles_for_groups({role_groups.get(group, group) for group in groups}) == roles


def test_roles_superusers_have_every_role(user: User) -> None:
    user.is_superuser = True

    assert user_roles(user) == {DATA, SUPPORT}


def test_roles_none_for_inactive_or_anonymous(user: User) -> None:
    set_roles(user, {DATA})
    user.is_active = False

    assert user_roles(user) == set()
    assert user_roles(AnonymousUser()) == set()


def test_roles_read_from_the_groups_once(
    user: User, django_assert_num_queries: Callable[..., object]
) -> None:
    Group.objects.create(name=SUPPORT).user_set.add(user)
    fresh = User.objects.get(pk=user.pk)

    with django_assert_num_queries(1):  # type: ignore[attr-defined]
        assert has_role(fresh, SUPPORT) and not has_role(fresh, DATA)


def test_set_roles_adds_and_removes(user: User) -> None:
    set_roles(user, {DATA, SUPPORT})
    set_roles(user, {SUPPORT})

    fresh = User.objects.get(pk=user.pk)
    assert set(fresh.groups.values_list("name", flat=True)) == {SUPPORT}


def test_set_roles_leaves_other_groups_alone(user: User) -> None:
    user.groups.add(Group.objects.create(name="something-else"))

    set_roles(user, set())

    assert list(user.groups.values_list("name", flat=True)) == ["something-else"]


def test_access_support_lands_on_diagnostics(support_client: Client) -> None:
    assert support_client.get(reverse("start")).status_code == HTTPStatus.OK


def test_access_data_lands_on_the_tables(data_client: Client) -> None:
    response = data_client.get(reverse("start"))

    assert response["Location"] == reverse("admin:index")


def test_access_no_role_is_refused(make_client: Callable[..., Client]) -> None:
    assert make_client().get(reverse("start")).status_code == HTTPStatus.FORBIDDEN


def test_access_data_cannot_open_cases(data_client: Client, case_url: str) -> None:
    assert data_client.get(case_url).status_code == HTTPStatus.FORBIDDEN
    cases = reverse("admin:diagnostics_case_changelist")
    assert data_client.get(cases).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize(
    "url",
    [
        reverse("admin:ocpp_chargepointv16_changelist"),
        reverse("deployment-status"),
    ],
)
def test_access_support_cannot_query_the_data(support_client: Client, url: str) -> None:
    assert support_client.get(url).status_code == HTTPStatus.FORBIDDEN


def test_access_support_cannot_switch_tenant(support_client: Client) -> None:
    response = support_client.post(reverse("switch-tenant"), {"tenant": "eosgie"})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize(
    ("role", "shown", "hidden"),
    [
        (SUPPORT, b"Diagnostics</a>", b'name="tenant"'),
        (DATA, b"Deployments</a>", b"Diagnostics</a>"),
    ],
)
def test_access_header_links_follow_the_role(
    make_client: Callable[..., Client], role: str, shown: bytes, hidden: bytes
) -> None:
    content = make_client(role).get(reverse("admin:index")).content

    assert shown in content and hidden not in content


def test_access_admin_index_shows_each_role_its_part(
    make_client: Callable[..., Client],
) -> None:
    support = make_client(SUPPORT).get(reverse("admin:index")).content
    data = make_client(DATA, username="dan").get(reverse("admin:index")).content

    cases = reverse("admin:diagnostics_case_changelist").encode()
    tables = reverse("admin:app_list", args=["ocpp"]).encode()
    assert cases in support and tables not in support
    assert tables in data and cases not in data


@pytest.mark.parametrize(
    ("role", "shown", "hidden"),
    [
        (SUPPORT, ["start", "guide", "admin:diagnostics_case_changelist"], ["deployment-status"]),
        (DATA, ["deployment-status"], ["start", "guide", "admin:diagnostics_case_changelist"]),
    ],
)
def test_access_admin_index_start_here_follows_the_role(
    make_client: Callable[..., Client], role: str, shown: list[str], hidden: list[str]
) -> None:
    content = make_client(role).get(reverse("admin:index")).content.decode()
    start_here = content.split("Start here", 1)[1].split("</table>", 1)[0]

    for name in shown + ["django-admindocs-docroot"]:
        assert f'href="{reverse(name)}"' in start_here, name
    for name in hidden:
        assert f'href="{reverse(name)}"' not in start_here, name
