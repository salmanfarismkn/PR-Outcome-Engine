from __future__ import annotations

from sqlalchemy.orm import Session

from app.commit.schemas import CommitImportSummary
from app.commit.service import CommitService
from app.github.service import GitHubService
from app.pull_request.models import PullRequest
from app import pull_request
from app import db


class CommitSyncService:
    def __init__(self) -> None:
        self._github = GitHubService()
        self._commit_service = CommitService()

    def import_commits(
        self,
        db: Session,
        pull_request: PullRequest,
    ) -> CommitImportSummary:

        print(
            "[webhook-debug] commit sync: second GitHub commits request started",
            flush=True,
        )
        commits = self._github.list_commits(
            owner=pull_request.repository.owner,
            repository=pull_request.repository.name,
            pull_number=pull_request.number,
        )
        print(
            "[webhook-debug] commit sync: second GitHub commits request returned; "
            f"count={len(commits)}",
            flush=True,
        )

        print("[webhook-debug] commit sync: commit import started", flush=True)
        result = self._commit_service.import_commits(
            db=db,
            pull_request_id=pull_request.id,
            commits=commits,
        )
        print(
            "[webhook-debug] commit sync: commit import returned; "
            f"imported={result.imported}, skipped={result.skipped}",
            flush=True,
        )
        return result

