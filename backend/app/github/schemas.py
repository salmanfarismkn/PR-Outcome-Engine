from pydantic import BaseModel
from datetime import datetime

from pydantic import BaseModel

class GitHubOwner(BaseModel):
    id: int
    login: str


class GitHubRepositoryPermissions(BaseModel):
    admin: bool
    maintain: bool
    push: bool
    triage: bool
    pull: bool


class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    description: str | None
    default_branch: str
    owner: GitHubOwner
    permissions: GitHubRepositoryPermissions | None = None


class GitHubUser(BaseModel):
    id: int
    login: str
    name: str | None
    avatar_url: str
    html_url: str
    public_repos: int

class RepositoryImportSummary(BaseModel):
    imported: int
    skipped: int
    total: int


class GitHubPullRequestUser(BaseModel):
    login: str


class GitHubPullRequestBranch(BaseModel):
    ref: str


class GitHubPullRequest(BaseModel):
    id: int
    number: int
    title: str
    state: str
    draft: bool

    user: GitHubPullRequestUser

    base: GitHubPullRequestBranch
    head: GitHubPullRequestBranch

    merged_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

class GitHubCommitAuthor(BaseModel):
    name: str
    email: str
    date: datetime


class GitHubCommitInfo(BaseModel):
    message: str
    author: GitHubCommitAuthor


class GitHubCommit(BaseModel):
    sha: str
    commit: GitHubCommitInfo
    

class GitHubChangedFile(BaseModel):
    filename: str
    status: str
    previous_filename: str | None = None
    additions: int
    deletions: int
    changes: int
    patch: str | None = None

class GitHubReviewUser(BaseModel):
    login: str


class GitHubReview(BaseModel):
    id: int
    user: GitHubReviewUser | None
    state: str
    body: str | None
    submitted_at: datetime | None


class GitHubCheckRun(BaseModel):
    id: int
    name: str
    status: str
    conclusion: str | None
    details_url: str | None
    started_at: datetime | None
    completed_at: datetime | None