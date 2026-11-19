from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings

REQUEST_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class WorkflowRun:
    run_number: int
    status: str  # queued / in_progress / completed
    conclusion: str | None  # success / failure / cancelled / ... once completed
    head_sha: str
    commit_message: str
    actor: str
    html_url: str
    run_started_at: datetime
    updated_at: datetime

    @property
    def short_sha(self) -> str:
        return self.head_sha[:7]

    @property
    def in_progress(self) -> bool:
        return self.status != "completed"


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_run(payload: dict[str, Any]) -> WorkflowRun:
    head_commit = payload.get("head_commit") or {}
    return WorkflowRun(
        run_number=payload["run_number"],
        status=payload["status"],
        conclusion=payload["conclusion"],
        head_sha=payload["head_sha"],
        commit_message=(head_commit.get("message") or "").splitlines()[0] if head_commit else "",
        actor=(payload.get("actor") or {}).get("login", ""),
        html_url=payload["html_url"],
        run_started_at=parse_timestamp(payload["run_started_at"]),
        updated_at=parse_timestamp(payload["updated_at"]),
    )


class GitHubClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url=settings.GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def repo_path(self, repository: str) -> str:
        return f"/repos/{settings.GITHUB_ORG}/{repository}"

    def latest_run(self, repository: str, workflow_file: str, branch: str) -> WorkflowRun | None:
        response = self.client.get(
            f"{self.repo_path(repository)}/actions/workflows/{workflow_file}/runs",
            params={"branch": branch, "event": "push", "per_page": 1},
        )
        response.raise_for_status()
        runs = response.json()["workflow_runs"]
        return parse_run(runs[0]) if runs else None

    def commits_ahead(self, repository: str, base: str, head: str) -> int:
        """Commits on `head` that `base` doesn't have, e.g. staging work not released to main."""
        response = self.client.get(f"{self.repo_path(repository)}/compare/{base}...{head}")
        response.raise_for_status()
        return int(response.json()["ahead_by"])
