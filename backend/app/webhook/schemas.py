from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GitHubWebhookRepository(BaseModel):
    id: int
    name: str
    full_name: str
    owner: dict


class GitHubWebhookPullRequest(BaseModel):
    id: int
    number: int

    title: str

    state: str
    merged: bool

    merged_at: datetime | None
    closed_at: datetime | None

    model_config = ConfigDict(
        extra="ignore",
    )


class PullRequestWebhookPayload(BaseModel):
    action: str

    repository: GitHubWebhookRepository
    pull_request: GitHubWebhookPullRequest

    model_config = ConfigDict(
        extra="ignore",
    )

class GitHubWebhookUser(BaseModel):
    login: str
    id: int

    model_config = ConfigDict(
        extra="ignore",
    )


class GitHubPullRequestReview(BaseModel):
    id: int
    user: GitHubWebhookUser

    body: str | None

    state: str

    submitted_at: datetime | None

    html_url: str | None

    model_config = ConfigDict(
        extra="ignore",
    )


class PullRequestReviewWebhookPayload(BaseModel):
    action: str

    repository: GitHubWebhookRepository

    pull_request: GitHubWebhookPullRequest

    review: GitHubPullRequestReview

    model_config = ConfigDict(
        extra="ignore",
    )

class GitHubCheckRunPullRequest(BaseModel):
    number: int

    model_config = ConfigDict(
        extra="ignore",
    )


class GitHubCheckRunWebhook(BaseModel):
    id: int
    name: str

    status: str
    conclusion: str | None

    details_url: str | None

    started_at: datetime | None
    completed_at: datetime | None

    head_sha: str

    pull_requests: list["GitHubCheckRunPullRequest"] = Field(
        default_factory=list,
    )

    model_config = ConfigDict(
        extra="ignore",
    )


class CheckRunWebhookPayload(BaseModel):
    action: str

    repository: GitHubWebhookRepository

    check_run: GitHubCheckRunWebhook

    model_config = ConfigDict(
        extra="ignore",
    )

class GitHubPushCommit(BaseModel):
    id: str
    message: str
    timestamp: datetime | None

    author: dict | None
    committer: dict | None

    distinct: bool

    added: list[str]
    removed: list[str]
    modified: list[str]

    model_config = ConfigDict(
        extra="ignore",
    )

    @property
    def sha(self) -> str:
        return self.id

    @property
    def commit(self):
        # Provide a nested object-like interface similar to GitHubCommit
        class Author:
            def __init__(self, data: dict | None, timestamp: datetime | None):
                self.name = data.get("name") if data else None
                self.email = data.get("email") if data else None
                self.date = timestamp

        class CommitInfo:
            def __init__(self, message: str, author: dict | None, timestamp: datetime | None):
                self.message = message
                self.author = Author(author, timestamp)

        return CommitInfo(self.message, self.author, self.timestamp)



class GitHubPushHeadCommit(BaseModel):
    id: str
    message: str

    timestamp: datetime | None

    model_config = ConfigDict(
        extra="ignore",
    )


class PushWebhookPayload(BaseModel):
    ref: str

    before: str
    after: str

    repository: GitHubWebhookRepository

    created: bool
    deleted: bool
    forced: bool

    compare: str

    commits: list[GitHubPushCommit]

    head_commit: GitHubPushHeadCommit | None

    model_config = ConfigDict(
        extra="ignore",
    )