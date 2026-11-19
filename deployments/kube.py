from dataclasses import dataclass
from datetime import datetime
from functools import cache

from django.conf import settings
from kubernetes import client
from kubernetes import config
from kubernetes.client.exceptions import ApiException

# Annotation `kubectl rollout restart` stamps on the pod template; CI deploys only through it.
RESTARTED_AT_ANNOTATION = "kubectl.kubernetes.io/restartedAt"


class ClusterNotConfigured(Exception):
    pass


@dataclass(frozen=True)
class Rollout:
    cluster: str
    namespace: str
    deployment: str
    desired: int
    ready: int
    updated: int
    available: int
    image: str
    restarted_at: datetime | None
    pod_restarts: int
    progress_message: str

    @property
    def healthy(self) -> bool:
        return (
            self.ready >= self.desired
            and self.updated >= self.desired
            and self.available >= self.desired
        )


@cache
def api_client(cluster: str) -> client.ApiClient:
    path = settings.KUBECONFIGS.get(cluster)
    if not path:
        raise ClusterNotConfigured(f"No kubeconfig for cluster {cluster!r}")
    api: client.ApiClient = config.new_client_from_config(  # type: ignore[no-untyped-call]
        config_file=path
    )
    return api


def read_rollout(cluster: str, namespace: str, deployment: str) -> Rollout:
    api = api_client(cluster)
    apps_api = client.AppsV1Api(api)
    core_api = client.CoreV1Api(api)

    dep = apps_api.read_namespaced_deployment(deployment, namespace)
    # The client types every part of a deployment as optional; an existing one always has a pod
    # template, and a missing status just means nothing is ready yet.
    spec = dep.spec
    if spec is None or spec.template.spec is None:
        raise ApiException(reason=f"Deployment {namespace}/{deployment} has no pod template")
    status = dep.status or client.V1DeploymentStatus()
    metadata = spec.template.metadata
    annotations = (metadata.annotations if metadata else None) or {}
    restarted_at = annotations.get(RESTARTED_AT_ANNOTATION)
    conditions = {condition.type: condition for condition in status.conditions or []}
    progressing = conditions.get("Progressing")

    match_labels = spec.selector.match_labels or {}
    selector = ",".join(f"{key}={value}" for key, value in match_labels.items())
    pods = core_api.list_namespaced_pod(namespace, label_selector=selector).items
    pod_restarts = sum(
        container.restart_count
        for pod in pods
        if pod.status
        for container in pod.status.container_statuses or []
    )

    return Rollout(
        cluster=cluster,
        namespace=namespace,
        deployment=deployment,
        desired=spec.replicas or 0,
        ready=status.ready_replicas or 0,
        updated=status.updated_replicas or 0,
        available=status.available_replicas or 0,
        image=spec.template.spec.containers[0].image or "",
        restarted_at=datetime.fromisoformat(restarted_at) if restarted_at else None,
        pod_restarts=pod_restarts,
        progress_message=(progressing.message or "") if progressing else "",
    )
