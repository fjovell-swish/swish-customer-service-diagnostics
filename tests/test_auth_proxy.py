"""Sign-in through the auth proxy: RemoteUserBackend, allowed groups, the proxy secret."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse

from config.auth_proxy import GroupRemoteUserBackend

pytestmark = pytest.mark.django_db


@pytest.fixture
def page() -> str:
    return reverse("start")


@pytest.fixture
def outsider_headers() -> dict[str, str]:
    return {"HTTP_X_FORWARDED_USER": "bob@swish.example", "HTTP_X_FORWARDED_GROUPS": "eng"}


def test_proxy_group_member_gets_in_as_staff(page: str, proxy_headers: dict[str, str]) -> None:
    client = Client()

    assert client.get(page, **proxy_headers).status_code == 200
    user = User.objects.get(username="ana@swish.example")
    assert user.is_staff and not user.has_usable_password()
    assert client.get(page, **proxy_headers).status_code == 200  # session reused


def test_proxy_refuses_people_outside_the_groups(
    page: str, outsider_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    response = Client().get(page, **outsider_headers)

    assert response.status_code == 302 and "/admin/login/" in response["Location"]
    assert not User.objects.filter(username="bob@swish.example").exists()
    assert "refused" in caplog.text


def test_proxy_leaving_the_group_signs_you_out(
    page: str, proxy_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    client = Client()
    assert client.get(page, **proxy_headers).status_code == 200

    response = client.get(page, **(proxy_headers | {"HTTP_X_FORWARDED_GROUPS": "eng"}))

    assert response.status_code == 302


def test_proxy_no_header_means_signed_out(page: str, proxy_headers: dict[str, str]) -> None:
    client = Client()
    assert client.get(page, **proxy_headers).status_code == 200

    assert client.get(page).status_code == 302  # the proxy stopped vouching for this browser


def test_proxy_identity_headers_need_the_secret(
    page: str, proxy_headers: dict[str, str], proxy_secret: dict[str, str]
) -> None:
    assert Client().get(page, **proxy_headers).status_code == 302
    assert Client().get(page, **proxy_headers, HTTP_X_PROXY_SECRET="wrong").status_code == 302
    assert Client().get(page, **proxy_headers, **proxy_secret).status_code == 200


def test_proxy_backend_ignores_requests_without_a_user() -> None:
    backend = GroupRemoteUserBackend()

    assert backend.authenticate(None, "ana") is None


def test_proxy_backend_ignores_an_empty_user(rf: RequestFactory) -> None:
    assert GroupRemoteUserBackend().authenticate(rf.get("/"), "") is None


def test_proxy_existing_users_are_promoted_to_staff(
    page: str, proxy_headers: dict[str, str]
) -> None:
    User.objects.create_user("ana@swish.example")

    assert Client().get(page, **proxy_headers).status_code == 200
    assert User.objects.get(username="ana@swish.example").is_staff


def test_proxy_returning_staff_are_left_as_they_are(
    page: str, proxy_headers: dict[str, str]
) -> None:
    User.objects.create_user("ana@swish.example", is_staff=True, first_name="Ana")

    assert Client().get(page, **proxy_headers).status_code == 200
    user = User.objects.get(username="ana@swish.example")
    assert user.is_staff and user.first_name == "Ana"


def test_proxy_local_superusers_still_use_the_login_form(page: str) -> None:
    User.objects.create_superuser("dev", "dev@example.com", "pw")
    client = Client()

    assert client.login(username="dev", password="pw")  # ModelBackend, local settings only
    assert client.get(page).status_code == 200  # no proxy headers, not signed out
