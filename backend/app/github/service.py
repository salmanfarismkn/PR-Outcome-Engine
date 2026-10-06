from sqlalchemy import select
from sqlalchemy.orm import Session
from app.repository.models import Repository
from app.repository.schemas import RepositoryImportSummary
from app.github.client import GitHubClient
from app.core.config import get_settings

from app.github.schemas import GitHubChangedFile, GitHubPullRequest, GitHubRepository
from app.pull_request.schemas import PullRequestImportSummary
from app.github.schemas import GitHubCommit
from app.github.schemas import GitHubReview
from app.github.schemas import GitHubCheckRun


class GitHubService:
    def __init__(self):
        settings = get_settings()
        self._client = GitHubClient(
            base_url=settings.github_api_url,
            token=settings.github_token,
        )

    def get_authenticated_user(self):
        return self._client.get_authenticated_user()

    def get_repository(self, owner: str, repository: str) -> GitHubRepository:
        return self._client.get_repository(owner, repository)

    def close(self) -> None:
        self._client.close()

    def list_repositories(self, db: Session) -> list[Repository]:
        # Query repositories stored in your DB
        return list(
            db.scalars(
                select(Repository).order_by(Repository.id)
            )
        )

    def list_pull_requests(
        self,
        owner: str,
        repository: str,
    ) -> list[GitHubPullRequest]:
        return self._client.list_pull_requests(
            owner,
            repository,
        )

    def list_commits(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> list[GitHubCommit]:
        return self._client.list_commits(
            owner,
            repository,
            pull_number,
        )
    
    def list_changed_files(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> list[GitHubChangedFile]:
        return self._client.list_changed_files(owner, repository, pull_number)

    def list_reviews(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> list[GitHubReview]:

        return self._client.list_reviews(
            owner,
            repository,
            pull_number,
        )

    def list_check_runs(
        self,
        owner: str,
        repository: str,
        ref: str,
    ) -> list[GitHubCheckRun]:

        return self._client.list_check_runs(
            owner,
            repository,
            ref,
        )

    def get_pull_request(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> GitHubPullRequest:

        return self._client.get_pull_request(
            owner,
            repository,
            pull_number,
        )

    def get_commit(
        self,
        owner: str,
        repository: str,
        sha: str,
    ):
        return self._client.get_commit(
            owner=owner,
            repository=repository,
            sha=sha,
        )

    def create_pull_request(
        self,
        owner: str,
        repository: str,
        *,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> GitHubPullRequest:
        return self._client.create_pull_request(
            owner=owner,
            repository=repository,
            title=title,
            body=body,
            head=head,
            base=base,
        )


    def merge_pull_request(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> dict:
        return self._client.merge_pull_request(
            owner=owner,
            repository=repository,
            pull_number=pull_number,
        )