from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.webhook.exceptions import DuplicateWebhookDelivery
from app.webhook.models import WebhookEvent

logger = logging.getLogger(__name__)


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
            db.refresh(event)
        except IntegrityError as exc:
            db.rollback()
            if not self._is_delivery_unique_conflict(exc):
                raise

            existing = self.get_event(db, delivery_id)
            if existing is None:
                raise
            raise DuplicateWebhookDelivery(existing) from exc
        except SQLAlchemyError:
            db.rollback()
            raise

        return event

    @staticmethod
    def _is_delivery_unique_conflict(error: IntegrityError) -> bool:
        original = error.orig
        sqlstate = getattr(original, "pgcode", None) or getattr(
            original,
            "sqlstate",
            None,
        )
        if sqlstate == "23505":
            constraint_name = getattr(
                getattr(original, "diag", None),
                "constraint_name",
                None,
            )
            return constraint_name in {
                "webhook_event_delivery_id_key",
                "uq_webhook_event_delivery_id",
            }

        return "delivery_id" in str(original)

    def mark_pending(
        self,
        db: Session,
        event: WebhookEvent,
        reason: str,
    ) -> None:
        previous_status = event.status
        event.status = "pending"
        event.error_message = reason

        try:
            db.commit()
            logger.info(
                "Webhook status changed event_id=%s delivery_id=%s "
                "event_type=%s previous_status=%s new_status=pending "
                "attempt_count=%s",
                getattr(event, "id", None),
                getattr(event, "delivery_id", None),
                getattr(event, "event_type", None),
                previous_status,
                event.attempt_count,
            )
        except SQLAlchemyError:
            db.rollback()
            raise

    def mark_processing(
        self,
        db: Session,
        event: WebhookEvent,
    ) -> None:
        previous_status = event.status
        event.status = "processing"
        event.error_message = None
        event.attempt_count = getattr(event, "attempt_count", 0) + 1
        event.last_attempt_at = datetime.now(UTC)

        try:
            db.commit()
            logger.info(
                "Webhook status changed event_id=%s delivery_id=%s "
                "event_type=%s previous_status=%s new_status=processing "
                "attempt_count=%s",
                getattr(event, "id", None),
                getattr(event, "delivery_id", None),
                getattr(event, "event_type", None),
                previous_status,
                event.attempt_count,
            )
        except SQLAlchemyError:
            db.rollback()
            raise

    def mark_processed(
        self,
        db: Session,
        event: WebhookEvent,
    ) -> None:
        previous_status = event.status
        event.status = "processed"
        event.error_message = None
        event.last_error_at = None

        try:
            db.commit()
            logger.info(
                "Webhook status changed event_id=%s delivery_id=%s "
                "event_type=%s previous_status=%s new_status=processed "
                "attempt_count=%s",
                getattr(event, "id", None),
                getattr(event, "delivery_id", None),
                getattr(event, "event_type", None),
                previous_status,
                event.attempt_count,
            )
        except SQLAlchemyError:
            db.rollback()
            raise

    def mark_failed(
        self,
        db: Session,
        event: WebhookEvent,
        error_message: str,
    ) -> None:
        previous_status = event.status
        event.status = "failed"
        event.error_message = error_message
        event.last_error_at = datetime.now(UTC)

        try:
            db.commit()
            logger.warning(
                "Webhook status changed event_id=%s delivery_id=%s "
                "event_type=%s previous_status=%s new_status=failed "
                "attempt_count=%s failure_category=handler",
                getattr(event, "id", None),
                getattr(event, "delivery_id", None),
                getattr(event, "event_type", None),
                previous_status,
                event.attempt_count,
            )
        except SQLAlchemyError:
            db.rollback()
            raise

    def mark_retryable_failure(
        self,
        db: Session,
        event: WebhookEvent,
        error_message: str,
        exhausted: bool,
    ) -> None:
        previous_status = event.status
        event.status = "failed" if exhausted else "received"
        event.error_message = error_message
        event.last_error_at = datetime.now(UTC)

        try:
            db.commit()
            logger.warning(
                "Webhook recovery status changed event_id=%s "
                "delivery_id=%s event_type=%s previous_status=%s "
                "new_status=%s attempt_count=%s failure_category=handler "
                "exhausted=%s",
                getattr(event, "id", None),
                getattr(event, "delivery_id", None),
                getattr(event, "event_type", None),
                previous_status,
                event.status,
                event.attempt_count,
                exhausted,
            )
        except SQLAlchemyError:
            db.rollback()
            raise



    @staticmethod
    def parse_payload(
        payload: bytes,
    ) -> dict:

        return json.loads(
            payload.decode("utf-8")
        )