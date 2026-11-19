# What gets deployed where.
#
# Mirrors each service's `.github/workflows/ci-cd.y*ml`: a push to a branch builds the image,
# pushes it to ACR and `kubectl rollout restart`s these deployments. Update this file when a
# service's CI changes its targets.
from dataclasses import dataclass


@dataclass(frozen=True)
class Environment:
    name: str
    branch: str


@dataclass(frozen=True)
class KubeTarget:
    cluster: str  # key of settings.KUBECONFIGS
    namespace: str
    deployment: str


@dataclass(frozen=True)
class Service:
    name: str
    repository: str
    workflow_file: str
    targets: dict[str, tuple[KubeTarget, ...]]  # environment name -> deployments restarted


STAGING = Environment(name="staging", branch="staging")
PRODUCTION = Environment(name="production", branch="main")
ENVIRONMENTS = (STAGING, PRODUCTION)


def same_on_both_clusters(*targets: tuple[str, str]) -> dict[str, tuple[KubeTarget, ...]]:
    return {
        STAGING.name: tuple(KubeTarget("staging", namespace, name) for namespace, name in targets),
        PRODUCTION.name: tuple(
            KubeTarget("production", namespace, name) for namespace, name in targets
        ),
    }


AIRFLOW_DEPLOYMENTS = tuple(
    ("airflow", f"swish-airflow-{component}")
    for component in ("scheduler", "webserver", "worker", "triggerer")
)

SERVICES = (
    Service(
        name="central-system",
        repository="central-system",
        workflow_file="ci-cd.yml",
        targets=same_on_both_clusters(("ocpp-central-system", "ocpp-central-system")),
    ),
    Service(
        name="api-ocpp",
        repository="api-ocpp",
        workflow_file="ci-cd.yml",
        targets={
            STAGING.name: (KubeTarget("staging", "ocpp-api", "ocpp-api"),),
            # On main the same image is also restarted as csms-api on the CSMS cluster.
            PRODUCTION.name: (
                KubeTarget("production", "ocpp-api", "ocpp-api"),
                KubeTarget("csms-production", "csms-api", "csms-api"),
            ),
        },
    ),
    Service(
        name="api-gateway",
        repository="api-gateway",
        workflow_file="ci-cd.yml",
        targets=same_on_both_clusters(("api-gateway", "api-gateway")),
    ),
    Service(
        name="api-gireve",
        repository="api-gireve",
        workflow_file="ci-cd.yml",
        targets=same_on_both_clusters(("api-gireve", "api-gireve")),
    ),
    Service(
        name="workflow",
        repository="workflow",
        workflow_file="ci-cd.yaml",
        targets=same_on_both_clusters(*AIRFLOW_DEPLOYMENTS),
    ),
)
