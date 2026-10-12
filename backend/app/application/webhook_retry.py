from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.review_webhook import ReviewWebhookService
from app.pull_request.models import PullRequest
from app.webhook.exceptions import WebhookDependencyPending
from app.webhook.models import WebhookEvent
from app.webhook.schemas import PullRequestReviewWebhookPayload
from app.webhook.service import WebhookService

logger = logging.getLogger(__name__)


class WebhookRetryService:

    def __init__(self) -> None:
        self._review_service = ReviewWebhookService()
        self._webhook_service = WebhookService()

    def get_pending_events(
        self,
        db: Session,
        limit: int | None = 50,
        event_type: str | None = None,
    ) -> list[WebhookEvent]:
        query = (
            select(WebhookEvent)
            .where(WebhookEvent.status == "pending")
            .order_by(WebhookEvent.created_at)
        )
        if event_type is not None:
            query = query.where(WebhookEvent.event_type == event_type)
        if limit is not None:
            query = query.limit(limit)
        return list(db.scalars(query))

    def retry_pending_review_events(
        self,
        db: Session,
        pull_request: PullRequest,
    ) -> int:
        pending_events = self.get_pending_events(
            db,
            limit=None,
            event_type="pull_request_review",
        )
        processed_count = 0

        for event in pending_events:
            try:
                payload = PullRequestReviewWebhookPayload.model_validate(
                    json.loads(event.payload)
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._webhook_service.mark_failed(
                    db,
                    event,
                    f"Stored review webhook payload is invalid: {exc}",
                )
                logger.exception(
                    "Unable to replay pending review delivery %s",
                    event.delivery_id,
                )
                continue

            if (
                payload.repository.id != pull_request.repository.github_id
                or payload.pull_request.id != pull_request.github_id
            ):
                continue

            self._webhook_service.mark_processing(db, event)
            try:
                self._review_service.process(db, payload)
            except WebhookDependencyPending as exc:
                self._webhook_service.mark_pending(
                    db,
                    event,
                    str(exc),
                )
                logger.warning(
                    "Review delivery %s remains pending: %s",
                    event.delivery_id,
                    exc,
                )
                raise
            except ValueError as exc:
                self._webhook_service.mark_failed(
                    db,
                    event,
                    str(exc),
                )
                logger.exception(
                    "Review delivery %s cannot be replayed",
                    event.delivery_id,
                )
                raise
            except Exception as exc:
                self._webhook_service.mark_pending(
                    db,
                    event,
                    str(exc),
                )
                logger.exception(
                    "Review delivery %s replay failed; keeping it pending",
                    event.delivery_id,
                )
                raise
            else:
                self._webhook_service.mark_processed(db, event)
                processed_count += 1

        return processed_count