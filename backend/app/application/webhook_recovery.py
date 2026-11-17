from __future__ import annotations

import logging
from time import perf_counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Callable

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.webhook.exceptions import WebhookDependencyPending
from app.webhook.models import WebhookEvent
from app.webhook.service import WebhookService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.webhook.dispatcher import WebhookDispatcher

RECOVERABLE_EVENT_TYPES = frozenset(
    {
        "pull_request",
        "pull_request_review",
        "check_run",
        "push",
    }
)


@dataclass(frozen=True)
class WebhookRecoveryCandidate:
    event_id: int
    delivery_id: str
    event_type: str
    status: str
    reference_time: datetime
    attempt_count: int
    payload: str

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - self.reference_time


@dataclass
class WebhookRecoverySummary:
    examined: int = 0
    eligible: int = 0
    recovered: int = 0
    skipped: int = 0
    failed: int = 0
    events: list[WebhookRecoveryCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class WebhookOperationalMetrics:
    total: int
    received: int
    processing: int
    pending: int
    processed: int
    failed: int
    exhausted: int
    eligible_for_recovery: int
    oldest_unrecovered_age: timedelta | None
    recovery_attempts: int = 0


class WebhookRecoveryService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        dispatcher: WebhookDispatcher | None = None,
    ) -> None:
        self._session_factory = session_factory
        if dispatcher is None:
            from app.webhook.dispatcher import WebhookDispatcher

            dispatcher = WebhookDispatcher()
        self._dispatcher = dispatcher
        self._webhook_service = WebhookService()

    @staticmethod
    def _stale_filter(
        stale_before: datetime,
        max_attempts: int,
    ):
        reference_time = func.coalesce(
            WebhookEvent.last_attempt_at,
            WebhookEvent.updated_at,
            WebhookEvent.created_at,
        )
        return and_(
            WebhookEvent.status.in_(("received", "processing")),
            WebhookEvent.attempt_count < max_attempts,
            reference_time <= stale_before,
        )

    def list_stale_events(
        self,
        db: Session,
        stale_before: datetime,
        max_attempts: int,
        limit: int,
    ) -> list[WebhookRecoveryCandidate]:
        events = db.scalars(
            select(WebhookEvent)
            .where(self._stale_filter(stale_before, max_attempts))
            .where(WebhookEvent.event_type.in_(RECOVERABLE_EVENT_TYPES))
            .order_by(WebhookEvent.created_at)
            .limit(limit)
        ).all()
        return [self._candidate(event) for event in events]

    def get_operational_metrics(
        self,
        db: Session,
        stale_before: datetime,
        max_attempts: int,
        recovery_attempts: int = 0,
    ) -> WebhookOperationalMetrics:
        reference_time = func.coalesce(
            WebhookEvent.last_attempt_at,
            WebhookEvent.updated_at,
            WebhookEvent.created_at,
        )
        row = db.execute(
            select(
                func.count().label("total"),
                func.sum(case((WebhookEvent.status == "received", 1), else_=0)).label(
                    "received"
                ),
                func.sum(case((WebhookEvent.status == "processing", 1), else_=0)).label(
                    "processing"
                ),
                func.sum(case((WebhookEvent.status == "pending", 1), else_=0)).label(
                    "pending"
                ),
                func.sum(case((WebhookEvent.status == "processed", 1), else_=0)).label(
                    "processed"
                ),
                func.sum(case((WebhookEvent.status == "failed", 1), else_=0)).label(
                    "failed"
                ),
                func.sum(
                    case((WebhookEvent.attempt_count >= max_attempts, 1), else_=0)
                ).label("exhausted"),
                func.sum(
                    case(
                        (
                            self._stale_filter(stale_before, max_attempts),
                            1,
                        ),
                        else_=0,
                    )
                ).label("eligible"),
                func.min(
                    case(
                        (WebhookEvent.status.in_(("received", "processing")), reference_time),
                        else_=None,
                    )
                ).label("oldest"),
            )
        ).one()
        oldest = row.oldest
        if oldest is None:
            oldest_age = None
        else:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            oldest_age = datetime.now(UTC) - oldest
        return WebhookOperationalMetrics(
            total=row.total or 0,
            received=row.received or 0,
            processing=row.processing or 0,
            pending=row.pending or 0,
            processed=row.processed or 0,
            failed=row.failed or 0,
            exhausted=row.exhausted or 0,
            eligible_for_recovery=row.eligible or 0,
            oldest_unrecovered_age=oldest_age,
            recovery_attempts=recovery_attempts,
        )

    def claim_stale_event(
        self,
        db: Session,
        stale_before: datetime,
        max_attempts: int,
    ) -> WebhookRecoveryCandidate | None:
        try:
            event = db.scalar(
                select(WebhookEvent)
                .where(self._stale_filter(stale_before, max_attempts))
                .where(WebhookEvent.event_type.in_(RECOVERABLE_EVENT_TYPES))
                .order_by(WebhookEvent.created_at)
                .with_for_update(skip_locked=True)
            )
        except SQLAlchemyError:
            db.rollback()
            raise
        if event is None:
            db.rollback()
            return None

        previous_status = event.status
        event.status = "processing"
        event.attempt_count += 1
        event.last_attempt_at = datetime.now(UTC)
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise
        logger.info(
            "Webhook recovery claimed event_id=%s delivery_id=%s "
            "event_type=%s previous_status=%s new_status=processing "
            "attempt_count=%s",
            event.id,
            event.delivery_id,
            event.event_type,
            previous_status,
            event.attempt_count,
        )
        return self._candidate(event)

    @staticmethod
    def _candidate(event: WebhookEvent) -> WebhookRecoveryCandidate:
        reference_time = (
            event.last_attempt_at
            or event.updated_at
            or event.created_at
        )
        return WebhookRecoveryCandidate(
            event_id=event.id,
            delivery_id=event.delivery_id,
            event_type=event.event_type,
            status=event.status,
            reference_time=reference_time,
            attempt_count=event.attempt_count,
            payload=event.payload,
        )

    def recover(
        self,
        stale_before: datetime,
        max_attempts: int,
        limit: int,
    ) -> WebhookRecoverySummary:
        summary = WebhookRecoverySummary()

        for _ in range(limit):
            with self._session_factory() as claim_db:
                claim = self.claim_stale_event(
                    claim_db,
                    stale_before,
                    max_attempts,
                )

            if claim is None:
                break

            summary.examined += 1
            summary.eligible += 1
            summary.events.append(claim)
            logger.info(
                "Webhook recovery claimed event_id=%s delivery_id=%s "
                "event_type=%s status=processing "
                "attempt_count=%s age_seconds=%.1f",
                claim.event_id,
                claim.delivery_id,
                claim.event_type,
                claim.attempt_count,
                claim.age.total_seconds(),
            )
            with self._session_factory() as process_db:
                event = process_db.get(WebhookEvent, claim.event_id)
                if event is None:
                    summary.failed += 1
                    continue

                try:
                    started_at = perf_counter()
                    payload = WebhookService.parse_payload(
                        claim.payload.encode("utf-8")
                    )
                    self._dispatcher.dispatch(
                        db=process_db,
                        event_type=claim.event_type,
                        payload=payload,
                        delivery_id=claim.delivery_id,
                    )
                    duration_ms = (perf_counter() - started_at) * 1000
                    logger.info(
                        "Webhook recovery dispatch completed event_id=%s "
                        "delivery_id=%s event_type=%s duration_ms=%.1f",
                        claim.event_id,
                        claim.delivery_id,
                        claim.event_type,
                        duration_ms,
                    )
                except WebhookDependencyPending as exc:
                    self._webhook_service.mark_pending(
                        process_db,
                        event,
                        str(exc),
                    )
                    summary.skipped += 1
                except Exception as exc:
                    logger.exception(
                        "Webhook recovery dispatch failed event_id=%s "
                        "delivery_id=%s event_type=%s failure_category=handler",
                        claim.event_id,
                        claim.delivery_id,
                        claim.event_type,
                    )
                    self._webhook_service.mark_retryable_failure(
                        process_db,
                        event,
                        str(exc),
                        exhausted=claim.attempt_count >= max_attempts,
                    )
                    summary.failed += 1
                else:
                    self._webhook_service.mark_processed(
                        process_db,
                        event,
                    )
                    summary.recovered += 1

        return summary
