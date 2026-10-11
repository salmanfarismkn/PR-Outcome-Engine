from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.check.models import CheckRun
from app.commit.models import Commit
from app.application.check_sync import CheckSyncService
from app.application.outcome_evaluation import evaluate_pull_request_outcome
from app.feature.service import PRFeatureService
from app.pull_request.models import PullRequest
from app.repository.models import Repository
from app.webhook.exceptions import WebhookDependencyPending
from app.webhook.schemas import CheckRunWebhookPayload

class CheckRunWebhookService:

    def __init__(self) -> None:
        self._check_sync = CheckSyncService()
        self._feature_service = PRFeatureService()

    def process(
        self,
        db: Session,
        payload: CheckRunWebhookPayload,
    ) -> list[CheckRun]:

        if payload.action not in {
            "created",
            "rerequested",
            "completed",
        }:
            return []

        check_data = payload.check_run
        repository = db.scalar(
            select(Repository).where(
                Repository.owner == payload.repository.owner["login"],
                Repository.name == payload.repository.name,
            )
        )
        if repository is None:
            return []

        pull_request_numbers = {
            association.number
            for association in check_data.pull_requests
        }
        if pull_request_numbers:
            pull_requests = list(
                db.scalars(
                    select(PullRequest).where(
                        PullRequest.repository_id == repository.id,
                        PullRequest.number.in_(pull_request_numbers),
                    )
                ).all()
            )
            if not pull_requests:
                raise WebhookDependencyPending(
                    "Associated pull request has not been synchronized yet."
                )
            if {
                pull_request.number for pull_request in pull_requests
            } != pull_request_numbers:
                raise WebhookDependencyPending(
                    "Not all associated pull requests have been synchronized yet."
                )
        else:
            pull_requests = list(
                db.scalars(
                    select(PullRequest)
                    .join(Commit, Commit.pull_request_id == PullRequest.id)
                    .where(
                        PullRequest.repository_id == repository.id,
                        Commit.sha == check_data.head_sha,
                    )
                    .distinct()
                ).all()
            )

        refreshed_runs: list[CheckRun] = []
        for pull_request in pull_requests:
            self._check_sync.import_check_runs(
                db=db,
                pull_request=pull_request,
            )
            db.refresh(pull_request)
            self._feature_service.create_snapshot(
                db=db,
                pull_request=pull_request,
            )
            evaluate_pull_request_outcome(
                db=db,
                pull_request_id=pull_request.id,
            )
            check_run = db.scalar(
                select(CheckRun).where(
                    CheckRun.github_id == check_data.id,
                    CheckRun.pull_request_id == pull_request.id,
                )
            )
            if check_run is not None:
                refreshed_runs.append(check_run)
        return refreshed_runs
