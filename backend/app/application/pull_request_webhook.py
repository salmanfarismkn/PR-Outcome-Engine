from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.pull_request_sync import (
    PullRequestSyncService,
)
from app.pull_request.models import PullRequest
from app.repository.models import Repository
from app.webhook.schemas import PullRequestWebhookPayload
from app import db
from app.outcome.service import (
    OutcomeEvaluator,
)
from app import pull_request
from app.feature.service import PRFeatureService
from app.application.outcome_evaluation import (
    evaluate_pull_request_outcome,
)

SNAPSHOT_EVENTS = {
    "opened",
    "synchronize",
    "reopened",
    "closed",
    "review_requested",
}

class PullRequestWebhookService:

    def __init__(self) -> None:
        self._sync_service = PullRequestSyncService()
        self._outcome_service = OutcomeEvaluator()
        self._feature_service = PRFeatureService()


    def process(
        self,
        db: Session,
        payload: PullRequestWebhookPayload,
    ) -> PullRequest | None:

        print(
            "[webhook-debug] PR process: entered; "
            f"action={payload.action!r}, "
            f"github_id={payload.pull_request.id}",
            flush=True,
        )
        if payload.action not in {
            "opened",
            "reopened",
            "synchronize",
            "closed",
        }:
            print("[webhook-debug] PR process: action ignored", flush=True)
            return None

        print("[webhook-debug] PR process: repository query started", flush=True)
        repository = db.scalar(
            select(Repository).where(
                Repository.owner == payload.repository.owner["login"],
                Repository.name == payload.repository.name,
            )
        )
        print(
            "[webhook-debug] PR process: repository query returned; "
            f"found={repository is not None}",
            flush=True,
        )

        if repository is None:
            raise ValueError(
                "Repository from webhook does not exist locally."
            )

        print("[webhook-debug] PR process: pull request query started", flush=True)
        pull_request = db.scalar(
            select(PullRequest).where(
                PullRequest.github_id == payload.pull_request.id
            )
        )
        print(
            "[webhook-debug] PR process: pull request query returned; "
            f"found={pull_request is not None}",
            flush=True,
        )

        if pull_request is None:
            print("[webhook-debug] PR process: creating pull request", flush=True)
            pull_request = self._create_pull_request(
                db=db,
                repository=repository,
                payload=payload,
            )
        else:
            print("[webhook-debug] PR process: updating pull request", flush=True)
            self._update_pull_request(
                pull_request=pull_request,
                payload=payload,
            )

        print("[webhook-debug] PR process: initial commit started", flush=True)
        db.commit()
        print("[webhook-debug] PR process: initial commit returned", flush=True)
        print("[webhook-debug] PR process: refresh started", flush=True)
        db.refresh(pull_request)
        print("[webhook-debug] PR process: refresh returned", flush=True)

        # Synchronize the PR when new commits arrive.
        if payload.action == "synchronize":
            print("[webhook-debug] PR process: synchronize started", flush=True)
            self._sync_service.sync_pull_request(
                db=db,
                pull_request=pull_request,
            )
            print("[webhook-debug] PR process: synchronize returned", flush=True)

            print("[webhook-debug] PR process: sync commit started", flush=True)
            db.commit()
            print("[webhook-debug] PR process: sync commit returned", flush=True)
            print("[webhook-debug] PR process: sync refresh started", flush=True)
            db.refresh(pull_request)
            print("[webhook-debug] PR process: sync refresh returned", flush=True)

        # Record merge outcome.
        if (
            payload.action == "closed"
            and payload.pull_request.merged
        ):
            print("[webhook-debug] PR process: merged outcome started", flush=True)
            self._outcome_service.evaluate(
                db=db,
                pull_request=pull_request,
            )
            print("[webhook-debug] PR process: merged outcome returned", flush=True)


        # Build/update feature snapshot.
        if payload.action in SNAPSHOT_EVENTS:
            print("[webhook-debug] PR process: snapshot started", flush=True)
            self._feature_service.create_snapshot(
                db=db,
                pull_request=pull_request,
            )
            print("[webhook-debug] PR process: snapshot returned", flush=True)

        # Evaluate the latest available outcome evidence.
        print("[webhook-debug] PR process: final outcome started", flush=True)
        evaluate_pull_request_outcome(
            db=db,
            pull_request_id=pull_request.id,
        )
        print("[webhook-debug] PR process: final outcome returned", flush=True)

        print("[webhook-debug] PR process: returning", flush=True)
        return pull_request


    @staticmethod
    def _create_pull_request(
        db: Session,
        repository: Repository,
        payload: PullRequestWebhookPayload,
    ) -> PullRequest:

        github_pr = payload.pull_request


        pull_request = PullRequest(
            repository_id=repository.id,
            github_id=github_pr.id,
            number=github_pr.number,
            title=github_pr.title,
            state=github_pr.state,
            author=getattr(github_pr, "author", "unknown"),
            base_branch=getattr(github_pr, "base_branch", "main"),
            head_branch=getattr(github_pr, "head_branch", "unknown"),
            is_draft=getattr(github_pr, "is_draft", False),
            merged=github_pr.merged,
            merged_at=github_pr.merged_at,
            closed_at=github_pr.closed_at,
        )
        db.add(pull_request)


        return pull_request

    @staticmethod
    def _update_pull_request(
        pull_request: PullRequest,
        payload: PullRequestWebhookPayload,
    ) -> None:


        github_pr = payload.pull_request

        pull_request.number = github_pr.number
        pull_request.title = github_pr.title
        pull_request.author = getattr(github_pr, "author", "unknown")
        pull_request.base_branch = getattr(github_pr, "base_branch", "main")
        pull_request.head_branch = getattr(github_pr, "head_branch", "unknown")
        pull_request.is_draft = getattr(github_pr, "is_draft", False)
        pull_request.state = github_pr.state
        pull_request.merged = github_pr.merged
        pull_request.merged_at = github_pr.merged_at
        pull_request.closed_at = github_pr.closed_at
