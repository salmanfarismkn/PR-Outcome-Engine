from __future__ import annotations
from ast import List
from urllib import response

from fastapi import requests
import httpx
from app.github.schemas import GitHubChangedFile, GitHubPullRequest
from app.github.schemas import GitHubUser
from app.github.schemas import GitHubRepository
from app.github.schemas import GitHubCommit
from app.github.schemas import GitHubReview
from app.github.schemas import GitHubCheckRun

class GitHubClient:
    """Lightweight client for interacting with the GitHub REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def get_authenticated_user(self) -> GitHubUser:
        """Fetch the currently authenticated GitHub user."""

        response = self._client.get("/user")
        response.raise_for_status()

        return GitHubUser.model_validate(response.json())

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def list_repositories(self) -> list[GitHubRepository]:
        response = self._client.get(
            "/user/repos",
            params={
                "sort": "updated",
                "per_page": 100,
            },
        )
        response.raise_for_status()


        return [
            GitHubRepository.model_validate(repo)
            for repo in response.json()
        ]

    def list_pull_requests(
        self,
        owner: str,
        repository: str,
    ) -> list[GitHubPullRequest]:

        response = self._client.get(
            f"/repos/{owner}/{repository}/pulls",
            params={
                "state": "all",
                "per_page": 100,
            },
        )

        response.raise_for_status()

        return [
            GitHubPullRequest.model_validate(pr)
            for pr in response.json()
        ]

    def list_commits(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> list[GitHubCommit]:

        response = self._client.get(
            f"/repos/{owner}/{repository}/pulls/{pull_number}/commits",
        )

        response.raise_for_status()

        return [
            GitHubCommit.model_validate(commit)
            for commit in response.json()
    ]

    def list_changed_files(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> List[GitHubChangedFile]:
        response = self._client.get(
            f"/repos/{owner}/{repository}/pulls/{pull_number}/files"
        )
        response.raise_for_status()

        return [GitHubChangedFile.model_validate(item) for item in response.json()]

    def list_reviews(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> list[GitHubReview]:

        response = self._client.get(
            f"/repos/{owner}/{repository}/pulls/{pull_number}/reviews",
        )

        response.raise_for_status()

        return [
            GitHubReview.model_validate(review)
            for review in response.json()
        ]

    def list_check_runs(
        self,
        owner: str,
        repository: str,
        ref: str,
    ) -> list[GitHubCheckRun]:

        response = self._client.get(
            f"/repos/{owner}/{repository}/commits/{ref}/check-runs",
        )

        response.raise_for_status()

        data = response.json()

        return [
            GitHubCheckRun.model_validate(check_run)
            for check_run in data.get("check_runs", [])
        ]

    def get_pull_request(
        self,
        owner: str,
        repository: str,
        pull_number: int,
    ) -> GitHubPullRequest:

        response = self._client.get(
            f"/repos/{owner}/{repository}/pulls/{pull_number}",
        )

        response.raise_for_status()

        return GitHubPullRequest.model_validate(
            response.json()
        )

    def get_commit(
        self,
        owner: str,
        repository: str,
        sha: str,
    ):
        response = self._client.get(
            f"/repos/{owner}/{repository}/commits/{sha}",
        )

        response.raise_for_status()

        return response.json()

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
    response = self._client.post(
        f"/repos/{owner}/{repository}/pulls",
        json={
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        },
    )

    response.raise_for_status()

    return GitHubPullRequest.model_validate(
        response.json()
    )


def merge_pull_request(
    self,
    owner: str,
    repository: str,
    pull_number: int,
) -> dict:
    response = self._client.put(
        f"/repos/{owner}/{repository}/pulls/{pull_number}/merge",
        json={
            "merge_method": "squash",
        },
    )

    response.raise_for_status()

    return response.json()