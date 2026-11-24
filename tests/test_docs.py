"""The support reps' guide (/guide/) and admindocs (/admin/doc/)."""

from collections.abc import Callable
from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from config.roles import DATA
from config.roles import SUPPORT

pytestmark = pytest.mark.django_db


@pytest.fixture
def support_client(make_client: Callable[..., Client]) -> Client:
    return make_client(SUPPORT)


@pytest.fixture
def data_client(make_client: Callable[..., Client]) -> Client:
    return make_client(DATA)


@pytest.fixture
def guide_url() -> str:
    return reverse("guide")


def test_guide_for_support(support_client: Client, guide_url: str) -> None:
    response = support_client.get(guide_url)

    assert response.status_code == HTTPStatus.OK
    assert b"How to diagnose a charger" in response.content
    assert b"Create the Jira ticket" in response.content


def test_guide_not_for_data(data_client: Client, guide_url: str) -> None:
    assert data_client.get(guide_url).status_code == HTTPStatus.FORBIDDEN


def test_guide_linked_from_the_start_page(support_client: Client, guide_url: str) -> None:
    content = support_client.get(reverse("start")).content

    assert f'href="{guide_url}"'.encode() in content


@pytest.fixture
def case_docs_url() -> str:
    return reverse("django-admindocs-models-detail", args=["diagnostics", "case"])


@pytest.mark.parametrize("role", [SUPPORT, DATA])
def test_admindocs_for_every_role(make_client: Callable[..., Client], role: str) -> None:
    assert make_client(role).get(reverse("django-admindocs-docroot")).status_code == HTTPStatus.OK


def test_admindocs_model_pages_need_the_model_permission(
    support_client: Client, admin_client: Client, case_docs_url: str
) -> None:
    # Django's own rule: a model's page needs its view or change permission, which the roles
    # (groups without permissions) don't give; superusers have them all.
    assert support_client.get(case_docs_url).status_code == HTTPStatus.FORBIDDEN
    assert b"by question key" in admin_client.get(case_docs_url).content


def test_admindocs_linked_from_the_header(support_client: Client) -> None:
    content = support_client.get(reverse("start")).content

    assert f'href="{reverse("django-admindocs-docroot")}"'.encode() in content


def test_admindocs_view_docstrings(support_client: Client) -> None:
    url = reverse("django-admindocs-views-detail", args=["diagnostics.views.start"])

    assert b"Find a charger and start a case" in support_client.get(url).content


def test_admindocs_refuses_a_user_without_a_role(make_client: Callable[..., Client]) -> None:
    response = make_client().get(reverse("django-admindocs-docroot"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_admindocs_asks_anonymous_to_sign_in(client: Client) -> None:
    response = client.get(reverse("django-admindocs-docroot"))

    assert response.status_code == HTTPStatus.FOUND
    assert "/admin/login/" in response["Location"]
