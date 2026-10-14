from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.webhook.models import WebhookEvent
from sqlalchemy.exc import IntegrityError

class WebhookService:

    @staticmethod
    def verify_signature(
        payload: bytes,
        signature: str | None,
        secret: str,
    ) -> bool:

        if not signature or not secret:
            return False

        expected = (
            "sha256="
            + hmac.new(
                secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(
            expected,
            signature,
        )

    def get_event(
        self,
        db: Session,
        delivery_id: str,
    ) -> WebhookEvent | None:

        return db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.delivery_id == delivery_id
            )
        )

    def create_event(
        self,
        db: Session,
        delivery_id: str,
        event_type: str,
        payload: bytes,
    ) -> WebhookEvent:

        event = WebhookEvent(
            delivery_id=delivery_id,
            event_type=event_type,
            status="received",
            payload=payload.decode("utf-8"),
        )

        db.add(event)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            event.status = "failed"
            event.error_message = str(e)
            db.refresh(event)

        return event

    def mark_pending(
        self,
        db: Session,
        event: WebhookEvent,
        reason: str,
    ) -> None:

        event.status = "pending"
        event.error_message = reason

        db.commit()
        
    def mark_processing(
        self,
        db: Session,
        event: WebhookEvent,
    ) -> None:

        event.status = "processing"
        event.error_message = None

        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            event.status = "failed"
            event.error_message = str(e)

    def mark_processed(
        self,
        db: Session,
        event: WebhookEvent,
    ) -> None:

        event.status = "processed"
        event.error_message = None

        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            event.status = "failed"
            event.error_message = str(e)

    def mark_failed(
        self,
        db: Session,
        event: WebhookEvent,
        error_message: str,
    ) -> None:

        event.status = "failed"
        event.error_message = error_message



        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            event.status = "failed"
            event.error_message = str(e)


    @staticmethod
    def parse_payload(
        payload: bytes,
    ) -> dict:

        return json.loads(
            payload.decode("utf-8")
        )