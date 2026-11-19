import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum

import httpx
from django.conf import settings
from django.core.cache import cache
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from deployments.github import GitHubClient
from deployments.github import WorkflowRun
from deployments.kube import ClusterNotConfigured
from deployments.kube import Rollout
from deployments.kube import read_rollout
from deployments.registry import ENVIRONMENTS
from deployments.registry import PRODUCTION
from deployments.registry import SERVICES
from deployments.registry import STAGING
from deployments.registry import Environment
from deployments.registry import Service

log = logging.getLogger(__name__)

CACHE_KEY = "deployments:status"
MAX_WORKERS = 16

# Failures of one source shouldn't blank the whole page: they are shown on the affected row.
GITHUB_ERRORS = (httpx.HTTPError,)
KUBE_ERRORS = (ApiException, ConfigException, OSError)


class Health(StrEnum):
    HEALTHY = "healthy"
    DEPLOYING = "deploying"
    FAILED = "failed"
    DEGRADED = "degraded"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass
class KubeResult:
    cluster: str
    namespace: str
    deployment: str
    rollout: Rollout | None = None
    error: str = ""


@dataclass
class EnvironmentStatus:
    service: Service
    environment: Environment
    run: WorkflowRun | None = None
    run_error: str = ""
    kube: list[KubeResult] = field(default_factory=list)
    unreleased_commits: int | None = None
    health: Health = Health.UNKNOWN
    reason: str = ""


def evaluate(status: EnvironmentStatus) -> tuple[Health, str]:
    run = status.run
    if run is None:
        return Health.UNKNOWN, status.run_error or "No CI run found for this branch"
    if run.in_progress:
        return Health.DEPLOYING, f"CI run #{run.run_number} is {run.status.replace('_', ' ')}"
    if run.conclusion != "success":
        return Health.FAILED, f"CI run #{run.run_number} ended {run.conclusion}"

    rollouts = [result.rollout for result in status.kube if result.rollout]
    if len(rollouts) < len(status.kube):
        return Health.UNKNOWN, f"CI run #{run.run_number} succeeded; cluster state unavailable"
    unhealthy = [rollout for rollout in rollouts if not rollout.healthy]
    if unhealthy:
        names = ", ".join(
            f"{rollout.deployment} {rollout.ready}/{rollout.desired}" for rollout in unhealthy
        )
        return Health.DEGRADED, f"Not all replicas ready: {names}"
    # CI restarts the deployments at the end of the run, so a restart older than the run
    # start means the latest image was built but never rolled out.
    stale = [
        rollout
        for rollout in rollouts
        if rollout.restarted_at is None or rollout.restarted_at < run.run_started_at
    ]
    if stale:
        names = ", ".join(rollout.deployment for rollout in stale)
        return Health.STALE, f"Not restarted since CI run #{run.run_number}: {names}"
    return Health.HEALTHY, f"Running {run.short_sha}"


def fetch_run(
    github: GitHubClient, service: Service, environment: Environment
) -> tuple[WorkflowRun | None, str]:
    try:
        return github.latest_run(service.repository, service.workflow_file, environment.branch), ""
    except GITHUB_ERRORS as exc:
        log.warning(
            "GitHub run lookup failed for %s@%s: %s", service.repository, environment.branch, exc
        )
        return None, f"GitHub: {exc}"


def fetch_unreleased(github: GitHubClient, service: Service) -> int | None:
    try:
        return github.commits_ahead(
            service.repository, base=PRODUCTION.branch, head=STAGING.branch
        )
    except GITHUB_ERRORS as exc:
        log.warning("GitHub compare failed for %s: %s", service.repository, exc)
        return None


def fetch_kube(result: KubeResult) -> KubeResult:
    try:
        result.rollout = read_rollout(result.cluster, result.namespace, result.deployment)
    except ClusterNotConfigured as exc:
        # Expected wherever a cluster's kubeconfig isn't mounted (e.g. locally): no warning.
        result.error = str(exc)
    except KUBE_ERRORS as exc:
        log.warning(
            "Rollout lookup failed for %s/%s on %s: %s",
            result.namespace,
            result.deployment,
            result.cluster,
            exc,
        )
        result.error = str(exc)
    return result


def collect(github: GitHubClient | None = None) -> list[EnvironmentStatus]:
    github = github or GitHubClient()
    statuses = [
        EnvironmentStatus(
            service=service,
            environment=environment,
            kube=[
                KubeResult(target.cluster, target.namespace, target.deployment)
                for target in service.targets.get(environment.name, ())
            ],
        )
        for service in SERVICES
        for environment in ENVIRONMENTS
    ]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        runs = {
            id(status): pool.submit(fetch_run, github, status.service, status.environment)
            for status in statuses
        }
        unreleased = {
            service.name: pool.submit(fetch_unreleased, github, service) for service in SERVICES
        }
        kube_futures = [
            pool.submit(fetch_kube, result) for status in statuses for result in status.kube
        ]
        for future in kube_futures:
            future.result()
        for status in statuses:
            status.run, status.run_error = runs[id(status)].result()
            if status.environment == PRODUCTION:
                status.unreleased_commits = unreleased[status.service.name].result()
            status.health, status.reason = evaluate(status)
    return statuses


def get_statuses(refresh: bool = False) -> list[EnvironmentStatus]:
    if not refresh:
        cached: list[EnvironmentStatus] | None = cache.get(CACHE_KEY)
        if cached is not None:
            return cached
    statuses = collect()
    cache.set(CACHE_KEY, statuses, settings.DEPLOYMENT_STATUS_CACHE_SECONDS)
    return statuses
