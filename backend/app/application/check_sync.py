from __future__ import annotations

from sqlalchemy.orm import Session

from app.check.schemas import CheckRunImportSummary
from app.check.service import CheckRunService
from app.github.service import GitHubService
from app.pull_request.models import PullRequest


class CheckSyncService:

    def __init__(self) -> None:
        self._github = GitHubService()
        self._check_service = CheckRunService()

    def import_check_runs(
        self,
        db: Session,
        pull_request: PullRequest,
    ) -> CheckRunImportSummary:
        github_pr = self._github.get_pull_request(
            owner=pull_request.repository.owner,
            repository=pull_request.repository.name,
            pull_number=pull_request.number,
        )
        pull_request.head_sha = github_pr.head.sha

        check_runs = self._github.list_check_runs(
            owner=pull_request.repository.owner,
            repository=pull_request.repository.name,
            ref=github_pr.head.sha,
        )
        check_runs = [
            check_run
            for check_run in check_runs
            if not check_run.pull_requests
            or any(
                associated_pr.number == pull_request.number
                for associated_pr in check_run.pull_requests
            )
        ]

        return self._check_service.import_check_runs(
            db=db,
            pull_request_id=pull_request.id,
            check_runs=check_runs,
        )

    def close(self) -> None:
        self._github.close()
