from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from config.roles import DATA
from deployments import kube
from deployments import status as status_module
from deployments import views
from deployments.github import GitHubClient
from deployments.github import WorkflowRun
from deployments.kube import ClusterNotConfigured
from deployments.kube import Rollout
from deployments.registry import ENVIRONMENTS
from deployments.registry import SERVICES
from deployments.status import EnvironmentStatus
from deployments.status import Health
from deployments.status import KubeResult
from deployments.status import collect
from deployments.status import evaluate


def test_evaluate_healthy(
    make_status: Callable[..., EnvironmentStatus], make_run, make_rollout
) -> None:
    health, reason = evaluate(make_status(make_run(), [make_rollout()]))

    assert health == Health.HEALTHY
    assert reason == "Running 0123456"


def test_evaluate_unknown_without_run(
    make_status: Callable[..., EnvironmentStatus], make_rollout
) -> None:
    health, _ = evaluate(make_status(None, [make_rollout()]))

    assert health == Health.UNKNOWN


def test_evaluate_deploying_while_ci_runs(make_status, make_run, make_rollout) -> None:
    health, reason = evaluate(
        make_status(make_run(status="in_progress", conclusion=None), [make_rollout()])
    )

    assert health == Health.DEPLOYING
    assert "in progress" in reason


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_evaluate_failed_ci(make_status, make_run, make_rollout, conclusion: str) -> None:
    health, reason = evaluate(make_status(make_run(conclusion=conclusion), [make_rollout()]))

    assert health == Health.FAILED
    assert conclusion in reason


def test_evaluate_degraded_when_replicas_missing(make_status, make_run, make_rollout) -> None:
    health, reason = evaluate(make_status(make_run(), [make_rollout(ready=2)]))

    assert health == Health.DEGRADED
    assert "ocpp-api 2/4" in reason


def test_evaluate_stale_when_not_restarted_after_build(
    make_status, make_run, make_rollout, now: datetime
) -> None:
    rollout = make_rollout(restarted_at=now - timedelta(days=1))

    health, reason = evaluate(make_status(make_run(), [rollout]))

    assert health == Health.STALE
    assert "#42" in reason


def test_evaluate_stale_when_never_restarted(make_status, make_run, make_rollout) -> None:
    health, _ = evaluate(make_status(make_run(), [make_rollout(restarted_at=None)]))

    assert health == Health.STALE


def test_evaluate_unknown_when_cluster_unreachable(make_status, make_run, make_rollout) -> None:
    health, reason = evaluate(make_status(make_run(), [make_rollout(), None]))

    assert health == Health.UNKNOWN
    assert "cluster state unavailable" in reason


@pytest.fixture
def github_runs_payload() -> dict[str, Any]:
    return {
        "workflow_runs": [
            {
                "run_number": 7,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "abcdef1234567890",
                "head_commit": {"message": "Release\n\nbody"},
                "actor": {"login": "dev"},
                "html_url": "https://github.com/x/y/actions/runs/7",
                "run_started_at": "2026-11-16T11:50:00Z",
                "updated_at": "2026-11-16T11:55:00Z",
            }
        ]
    }


@pytest.fixture
def github() -> GitHubClient:
    return GitHubClient(httpx.Client(base_url="https://github.test"))


@respx.mock
def test_collect_combines_github_and_kube(
    github: GitHubClient,
    github_runs_payload: dict[str, Any],
    make_rollout: Callable[..., Rollout],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(url__regex=r".*/actions/workflows/.*/runs").respond(json=github_runs_payload)
    respx.get(url__regex=r".*/compare/main\.\.\.staging").respond(json={"ahead_by": 3})
    rollout = make_rollout(restarted_at=datetime.fromisoformat("2026-11-16T11:54:00+00:00"))
    monkeypatch.setattr(
        status_module, "read_rollout", lambda cluster, namespace, deployment: rollout
    )

    statuses = collect(github)

    assert len(statuses) == len(SERVICES) * len(ENVIRONMENTS)
    assert {status.health for status in statuses} == {Health.HEALTHY}
    production = [status for status in statuses if status.environment.name == "production"]
    assert {status.unreleased_commits for status in production} == {3}
    assert all(
        status.unreleased_commits is None for status in statuses if status not in production
    )


@respx.mock
def test_collect_reports_errors_per_row(
    github: GitHubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get(url__regex=r".*/runs").respond(status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    respx.get(url__regex=r".*/compare/.*").respond(status_code=HTTPStatus.NOT_FOUND)

    def no_cluster(cluster: str, namespace: str, deployment: str) -> Rollout:
        raise ClusterNotConfigured(f"No kubeconfig for cluster {cluster!r}")

    monkeypatch.setattr(status_module, "read_rollout", no_cluster)

    statuses = collect(github)

    assert {status.health for status in statuses} == {Health.UNKNOWN}
    assert all(status.run_error.startswith("GitHub:") for status in statuses)
    assert all(result.error for status in statuses for result in status.kube)


def test_github_latest_run_none_when_branch_has_no_runs(github: GitHubClient) -> None:
    with respx.mock:
        respx.get(url__regex=r".*/runs").respond(json={"workflow_runs": []})

        assert github.latest_run("api-ocpp", "ci-cd.yml", "main") is None


def test_github_latest_run_parses_first_line_of_commit(
    github: GitHubClient, github_runs_payload
) -> None:
    with respx.mock:
        route = respx.get(
            "https://github.test/repos/swish-charge/api-ocpp/actions/workflows/ci-cd.yml/runs"
        )
        route.respond(json=github_runs_payload)

        run = github.latest_run("api-ocpp", "ci-cd.yml", "staging")

    assert isinstance(run, WorkflowRun)
    assert run.commit_message == "Release"
    assert run.short_sha == "abcdef1"
    assert route.calls.last.request.url.params["branch"] == "staging"


# --- Kubernetes: reading a rollout ---


@pytest.fixture
def make_deployment() -> Callable[..., client.V1Deployment]:
    """A deployment as the Kubernetes API returns it."""

    def factory(**overrides: Any) -> client.V1Deployment:
        values: dict[str, Any] = {
            "spec": client.V1DeploymentSpec(
                replicas=2,
                selector=client.V1LabelSelector(match_labels={"app": "ocpp-api"}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        annotations={kube.RESTARTED_AT_ANNOTATION: "2026-11-16T11:54:00+00:00"}
                    ),
                    spec=client.V1PodSpec(
                        containers=[client.V1Container(name="api", image="acr/ocpp-api:main")]
                    ),
                ),
            ),
            "status": client.V1DeploymentStatus(
                ready_replicas=2,
                updated_replicas=2,
                available_replicas=2,
                conditions=[
                    client.V1DeploymentCondition(
                        type="Progressing", status="True", message="rolled out"
                    )
                ],
            ),
        }
        return client.V1Deployment(**(values | overrides))

    return factory


@pytest.fixture
def make_pod() -> Callable[..., client.V1Pod]:
    def factory(restarts: int) -> client.V1Pod:
        container = client.V1ContainerStatus(
            name="api", image="", image_id="", ready=True, restart_count=restarts
        )
        return client.V1Pod(status=client.V1PodStatus(container_statuses=[container]))

    return factory


@pytest.fixture
def fake_cluster(monkeypatch: pytest.MonkeyPatch) -> Callable[..., SimpleNamespace]:
    """Serve one deployment and its pods instead of a cluster."""

    def install(deployment: client.V1Deployment, pods: list[client.V1Pod]) -> SimpleNamespace:
        calls = SimpleNamespace(selector=None)

        def list_pods(namespace: str, label_selector: str) -> SimpleNamespace:
            calls.selector = label_selector
            return SimpleNamespace(items=pods)

        monkeypatch.setattr(kube, "api_client", lambda cluster: None)
        monkeypatch.setattr(
            kube.client,
            "AppsV1Api",
            lambda api: SimpleNamespace(read_namespaced_deployment=lambda name, ns: deployment),
        )
        monkeypatch.setattr(
            kube.client, "CoreV1Api", lambda api: SimpleNamespace(list_namespaced_pod=list_pods)
        )
        return calls

    return install


def test_kube_read_rollout(
    fake_cluster: Callable[..., SimpleNamespace],
    make_deployment: Callable[..., client.V1Deployment],
    make_pod: Callable[..., client.V1Pod],
) -> None:
    calls = fake_cluster(make_deployment(), [make_pod(1), make_pod(2), client.V1Pod()])

    rollout = kube.read_rollout("production", "ocpp-api", "ocpp-api")

    assert (rollout.desired, rollout.ready, rollout.updated, rollout.available) == (2, 2, 2, 2)
    assert rollout.healthy
    assert rollout.image == "acr/ocpp-api:main"
    assert rollout.restarted_at == datetime.fromisoformat("2026-11-16T11:54:00+00:00")
    assert (rollout.pod_restarts, rollout.progress_message) == (3, "rolled out")
    assert calls.selector == "app=ocpp-api"


def test_kube_read_rollout_never_restarted_nothing_ready(
    fake_cluster: Callable[..., SimpleNamespace],
    make_deployment: Callable[..., client.V1Deployment],
) -> None:
    deployment = make_deployment(status=None)
    deployment.spec.template.metadata = None
    deployment.spec.selector.match_labels = None
    fake_cluster(deployment, [])

    rollout = kube.read_rollout("production", "ocpp-api", "ocpp-api")

    assert (rollout.ready, rollout.restarted_at, rollout.progress_message) == (0, None, "")
    assert not rollout.healthy


def test_kube_read_rollout_without_pod_template(
    fake_cluster: Callable[..., SimpleNamespace],
    make_deployment: Callable[..., client.V1Deployment],
) -> None:
    deployment = make_deployment()
    deployment.spec.template.spec = None
    fake_cluster(deployment, [])

    with pytest.raises(ApiException, match="no pod template"):
        kube.read_rollout("production", "ocpp-api", "ocpp-api")


@pytest.fixture
def fresh_api_clients() -> Iterator[None]:
    kube.api_client.cache_clear()
    yield
    kube.api_client.cache_clear()


def test_kube_api_client_needs_a_kubeconfig(fresh_api_clients: None, settings: Any) -> None:
    settings.KUBECONFIGS = {}

    with pytest.raises(ClusterNotConfigured, match="production"):
        kube.api_client("production")


def test_kube_api_client_from_the_cluster_kubeconfig(
    fresh_api_clients: None, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.KUBECONFIGS = {"production": "/secrets/kubeconfig-production"}
    monkeypatch.setattr(kube.config, "new_client_from_config", lambda config_file: config_file)

    assert kube.api_client("production") == "/secrets/kubeconfig-production"


# --- Status: errors per row, cache ---


def test_fetch_kube_reports_cluster_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def unreachable(cluster: str, namespace: str, deployment: str) -> Rollout:
        raise OSError("connection refused")

    monkeypatch.setattr(status_module, "read_rollout", unreachable)

    result = status_module.fetch_kube(KubeResult("production", "ocpp-api", "ocpp-api"))

    assert (result.rollout, result.error) == (None, "connection refused")
    assert "Rollout lookup failed" in caplog.text


@pytest.fixture
def fake_collect(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def collect_once(github: GitHubClient | None = None) -> list[EnvironmentStatus]:
        calls.append(1)
        return []

    monkeypatch.setattr(status_module, "collect", collect_once)
    cache.delete(status_module.CACHE_KEY)
    return calls


def test_get_statuses_cached(fake_collect: list[int]) -> None:
    status_module.get_statuses()
    status_module.get_statuses()

    assert len(fake_collect) == 1


def test_get_statuses_refresh_bypasses_the_cache(fake_collect: list[int]) -> None:
    status_module.get_statuses()
    status_module.get_statuses(refresh=True)

    assert len(fake_collect) == 2


# --- The page ---


@pytest.mark.django_db
def test_deployment_status_page(
    make_client: Callable[..., Client],
    make_status: Callable[..., EnvironmentStatus],
    make_run: Callable[..., WorkflowRun],
    make_rollout: Callable[..., Rollout],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshes: list[bool] = []

    def statuses(refresh: bool = False) -> list[EnvironmentStatus]:
        refreshes.append(refresh)
        status = make_status(make_run(), [make_rollout()])
        status.health, status.reason = evaluate(status)
        return [status]

    monkeypatch.setattr(views, "get_statuses", statuses)

    response = make_client(DATA).get(reverse("deployment-status"), {"refresh": "1"})

    assert response.status_code == HTTPStatus.OK
    assert b"central-system" in response.content and b"healthy" in response.content
    assert refreshes == [True]
