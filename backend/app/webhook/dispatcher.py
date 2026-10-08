from __future__ import annotations

from sqlalchemy.orm import Session

from app.application.pull_request_webhook import (
    PullRequestWebhookService,
)
from app.webhook.schemas import PullRequestWebhookPayload
from app.application.review_webhook import (
    ReviewWebhookService,
)
from app.application.check_webhook import (
    CheckRunWebhookService,
)

from app.webhook.schemas import (
    CheckRunWebhookPayload,
)
from app.webhook.schemas import (
    PullRequestReviewWebhookPayload,
)
from app.application.push_webhook import (
    PushWebhookService,
)

from app.webhook.schemas import (
    PushWebhookPayload,
)

class WebhookDispatcher:

    def __init__(self) -> None:
        self._pull_request_service = (
            PullRequestWebhookService()
        )
        self._review_service = (
            ReviewWebhookService()
        )
        self._check_service = (
            CheckRunWebhookService()
        )
        self._push_service = (
            PushWebhookService()
        )

    def dispatch(
        self,
        db: Session,
        event_type: str,
        payload: dict,
        delivery_id: str,
    ) -> None:

        if event_type == "pull_request":
            self._handle_pull_request(
                db=db,
                payload=payload,
            )
            return

        if event_type == "pull_request_review":
            self._handle_pull_request_review(
                db=db,
                payload=payload,
            )
            return

        if event_type == "check_run":
            self._handle_check_run(
                db=db,
                payload=payload,
            )
            return
        
        if event_type == "push":
            self._handle_push(
                db=db,
                payload=payload,
                delivery_id=delivery_id,
            )
            return

    def _handle_pull_request(
        self,
        db: Session,
        payload: dict,
    ) -> None:

        print("[webhook-debug] pull_request: validating payload", flush=True)
        webhook_payload = (
            PullRequestWebhookPayload.model_validate(
                payload
            )
        )
        print(
            "[webhook-debug] pull_request: payload validated; "
            f"action={webhook_payload.action!r}, "
            f"number={webhook_payload.pull_request.number}",
            flush=True,
        )

        print("[webhook-debug] pull_request: process started", flush=True)
        self._pull_request_service.process(
            db=db,
            payload=webhook_payload,
        )
        print("[webhook-debug] pull_request: process returned", flush=True)

    def _handle_pull_request_review(
        self,
        db: Session,
        payload: dict,
    ) -> None:

        webhook_payload = (
            PullRequestReviewWebhookPayload.model_validate(
                payload
            )
        )

        self._review_service.process(
            db=db,
            payload=webhook_payload,
        )

    def _handle_check_run(
        self,
        db: Session,
        payload: dict,
    ) -> None:

        webhook_payload = (
            CheckRunWebhookPayload.model_validate(
                payload
            )
        )

        self._check_service.process(
            db=db,
            payload=webhook_payload,
        )

    def _handle_push(
        self,
        db: Session,
        payload: dict,
        delivery_id: str,
    ) -> None:

        webhook_payload = (
            PushWebhookPayload.model_validate(
                payload
            )
        )

        self._push_service.process(
            db=db,
            delivery_id=delivery_id,
            payload=webhook_payload,
        )