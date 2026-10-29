from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.push.models import PushEvent
from app.repository.models import Repository
from app.webhook.schemas import PushWebhookPayload
from app.application.push_commit_linker import (
    PushCommitLinker,
)
from app.application.revert_detection import (
    RevertDetectionService,
)
from app.commit.service import CommitService

class PushWebhookService:

    def __init__(self) -> None:
        self._commit_linker = PushCommitLinker()
        self._revert_detection = RevertDetectionService()
        self._commit_service = CommitService()

    def process(
        self,
        db: Session,
        delivery_id: str,
        payload: PushWebhookPayload,
    ) -> PushEvent | None:

        repository = db.scalar(
            select(Repository).where(
                Repository.owner == payload.repository.owner["login"],
                Repository.name == payload.repository.name
            )
        )

        if repository is None:
            raise ValueError(
                f"Repository {payload.repository.owner.login}/{payload.repository.name} "
                "from push webhook does not exist locally."
            )

        existing = db.scalar(
            select(PushEvent).where(PushEvent.delivery_id == delivery_id)
        )
        if existing is not None:
            return existing

        head_commit_message = None
        if payload.head_commit is not None:
            head_commit_message = payload.head_commit.message

        push_event = PushEvent(
            delivery_id=delivery_id,
            repository_id=repository.id,
            before_sha=payload.before,
            after_sha=payload.after,
            ref=payload.ref,
            commit_count=len(payload.commits),
            commit_shas=[commit.id for commit in payload.commits],
            head_commit_message=head_commit_message,
        )

        # Ensure commits are imported before revert detection
        self._sync_push_commits(db=db, repository=repository, payload=payload)

        for commit_sha in push_event.commit_shas:
            self._revert_detection.inspect_commit(
                db=db,
                repository_owner=repository.owner,
                repository_name=repository.name,
                commit_sha=commit_sha,
            )

        db.add(push_event)
        db.commit()
        db.refresh(push_event)

        existing_commits = self._commit_linker.find_existing_commits(
            db=db,
            push_event=push_event,
        )

        print("Push commits already synchronized:", len(existing_commits))

        return push_event

    def _sync_push_commits(
        self,
        db: Session,
        repository: Repository,
        payload: PushWebhookPayload,
    ) -> None:
        # Delegate commit creation to the existing CommitService
        self._commit_service.import_commits(
            db=db,
            pull_request_id=None,  # push events don’t prove PR linkage
            commits=payload.commits,
        )
