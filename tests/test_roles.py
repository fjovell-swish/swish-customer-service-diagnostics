"""The two ways in: `data` (query the data) and `support` (customer service), from proxy groups."""

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
        ({"swish-support"}, {SUPPORT}),
        ({"swish-data", "eng"}, {DATA}),
        ({"swish-ops"}, {DATA, SUPPORT}),
        ({"eng"}, set()),
    ],
)
def test_roles_for_groups(groups: set[str], roles: set[str]) -> None:
    assert roles_for_groups(groups) == roles


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


def test_proxy_roles_follow_the_groups_on_every_request(
    proxy_headers: dict[str, str],
) -> None:
    client = Client()
    assert client.get(reverse("start"), **proxy_headers).status_code == HTTPStatus.OK

    as_data = proxy_headers | {"HTTP_X_FORWARDED_GROUPS": "swish-data"}
    response = client.get(reverse("start"), **as_data)

    assert response["Location"] == reverse("admin:index")
    user = User.objects.get(username="ana@swish.example")
    assert set(user.groups.values_list("name", flat=True)) == {DATA}


@pytest.mark.django_db(databases="__all__")
@pytest.mark.usefixtures("ocpp_tables")
def test_proxy_both_roles_from_one_group(proxy_headers: dict[str, str]) -> None:
    client = Client()
    headers = proxy_headers | {"HTTP_X_FORWARDED_GROUPS": "swish-ops"}

    assert client.get(reverse("start"), **headers).status_code == HTTPStatus.OK
    changelist = reverse("admin:ocpp_chargepointv16_changelist")
    assert client.get(changelist, **headers).status_code == HTTPStatus.OK
