from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.application.webhook_recovery import WebhookRecoveryService
from app.webhook.exceptions import DuplicateWebhookDelivery
from app.webhook.models import WebhookEvent
from app.webhook.service import WebhookService

pytestmark = pytest.mark.postgres


def _delivery(prefix: str) -> str:
    return f"postgres-{prefix}-{uuid.uuid4()}"


def _insert_event(
    session: Session,
    *,
    delivery_id: str,
    status: str = "received",
    attempt_count: int = 0,
    stale: bool = True,
) -> WebhookEvent:
    now = datetime.now(UTC)
    timestamp = now - timedelta(hours=1) if stale else now
    event = WebhookEvent(
        delivery_id=delivery_id,
        event_type="pull_request_review",
        status=status,
        payload="{}",
        attempt_count=attempt_count,
        created_at=timestamp,
        updated_at=timestamp,
        last_attempt_at=timestamp if attempt_count else None,
    )
    session.add(event)
    session.commit()
    return event


def test_migration_head_and_recovery_columns(
    postgres_engine,
) -> None:
    with postgres_engine.connect() as connection:
        current = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert current == "7b3d4f1a2c6e"
        assert connection.execute(
            text(
                """
                SELECT is_identity
                FROM information_schema.columns
                WHERE table_name = 'webhook_event'
                  AND column_name = 'id'
                """
            )
        ).scalar_one() == "YES"
        indexes = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = 'webhook_event'
                    """
                )
            )
        }
        assert "ix_webhook_event_recovery" in indexes


def test_concurrent_duplicate_delivery_insertions(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("duplicate")
    cleanup_webhook_events.append(delivery_id)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def insert_event(event_id: int) -> None:
        with Session(postgres_engine) as session:
            barrier.wait()
            try:
                session.execute(
                    text(
                        """
                        INSERT INTO webhook_event
                        (delivery_id, event_type, status, payload,
                         attempt_count, created_at, updated_at)
                        VALUES
                        (:delivery_id, 'pull_request_review',
                         'received', '{}', 0, now(), now())
                        """
                    ),
                    {"delivery_id": delivery_id},
                )
                session.commit()
                results.append("inserted")
            except Exception:
                session.rollback()
                results.append("conflict")

    threads = [
        threading.Thread(target=insert_event, args=(1000001,)),
        threading.Thread(target=insert_event, args=(1000002,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["conflict", "inserted"]


def test_service_requeries_duplicate_delivery(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("service-duplicate")
    cleanup_webhook_events.append(delivery_id)
    service = WebhookService()

    with Session(postgres_engine) as first:
        original = service.create_event(
            first,
            delivery_id,
            "pull_request_review",
            b"{}",
        )

    with Session(postgres_engine) as second:
        with pytest.raises(DuplicateWebhookDelivery) as conflict:
            service.create_event(
                second,
                delivery_id,
                "pull_request_review",
                b"{}",
            )

    assert conflict.value.event.id == original.id


def test_concurrent_recovery_claims_are_atomic(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("claim")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as session:
        _insert_event(
            session,
            delivery_id=delivery_id,
        )

    barrier = threading.Barrier(2)
    claims: list[int | None] = []

    def claim() -> None:
        service = WebhookRecoveryService(lambda: None, dispatcher=SimpleNamespace())
        with Session(postgres_engine) as session:
            barrier.wait()
            candidate = service.claim_stale_event(
                session,
                datetime.now(UTC) - timedelta(minutes=15),
                max_attempts=3,
            )
            claims.append(candidate.event_id if candidate else None)

    threads = [threading.Thread(target=claim), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    non_null_claims = [value for value in claims if value is not None]
    assert len(non_null_claims) == 1
    assert len(claims) == 2
    with Session(postgres_engine) as session:
        event = session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.delivery_id == delivery_id
            )
        )
        assert event is not None
        assert event.status == "processing"
        assert event.attempt_count == 1


def test_skip_locked_does_not_claim_a_locked_event(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("locked")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as setup:
        _insert_event(
            setup,
            delivery_id=delivery_id,
        )

    locked = Session(postgres_engine)
    try:
        locked_event = locked.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.delivery_id == delivery_id)
            .with_for_update()
        )
        assert locked_event is not None
        service = WebhookRecoveryService(lambda: None, dispatcher=SimpleNamespace())
        with Session(postgres_engine) as contender:
            assert (
                service.claim_stale_event(
                    contender,
                    datetime.now(UTC) - timedelta(minutes=15),
                    max_attempts=3,
                )
                is None
            )
    finally:
        locked.rollback()
        locked.close()


def test_claim_attempt_count_persists_across_sessions(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("attempt")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as setup:
        _insert_event(
            setup,
            delivery_id=delivery_id,
        )

    service = WebhookRecoveryService(lambda: None, dispatcher=SimpleNamespace())
    with Session(postgres_engine) as first:
        candidate = service.claim_stale_event(
            first,
            datetime.now(UTC) - timedelta(minutes=15),
            max_attempts=3,
        )
    assert candidate is not None

    with Session(postgres_engine) as second:
        event = second.scalar(
            select(WebhookEvent).where(
                WebhookEvent.delivery_id == delivery_id
            )
        )
        assert event is not None
        assert event.status == "processing"
        assert event.attempt_count == 1


def test_crash_after_claim_can_be_reclaimed_when_stale(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("crash")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as setup:
        _insert_event(
            setup,
            delivery_id=delivery_id,
        )

    service = WebhookRecoveryService(lambda: None, dispatcher=SimpleNamespace())
    with Session(postgres_engine) as first:
        assert service.claim_stale_event(
            first,
            datetime.now(UTC) - timedelta(minutes=15),
            max_attempts=3,
        )

    with Session(postgres_engine) as mark_stale:
        mark_stale.execute(
            text(
                """
                UPDATE webhook_event
                SET last_attempt_at = now() - interval '1 hour',
                    updated_at = now() - interval '1 hour'
                WHERE delivery_id = :delivery_id
                """
            ),
            {"delivery_id": delivery_id},
        )
        mark_stale.commit()

    with Session(postgres_engine) as second:
        candidate = service.claim_stale_event(
            second,
            datetime.now(UTC) - timedelta(minutes=15),
            max_attempts=3,
        )
        assert candidate is not None
        assert candidate.attempt_count == 2


def test_recovery_handler_failure_is_persisted(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("failure")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as setup:
        _insert_event(
            setup,
            delivery_id=delivery_id,
        )

    dispatcher = SimpleNamespace(
        dispatch=lambda **_: (_ for _ in ()).throw(
            RuntimeError("integration handler failure")
        )
    )
    service = WebhookRecoveryService(lambda: Session(postgres_engine), dispatcher)
    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.failed == 1
    with Session(postgres_engine) as verify:
        event = verify.scalar(
            select(WebhookEvent).where(
                WebhookEvent.delivery_id == delivery_id
            )
        )
        assert event is not None
        assert event.status == "received"
        assert event.attempt_count == 1
        assert event.error_message == "integration handler failure"


def test_malformed_payload_is_persisted_as_failure(
    postgres_engine,
    cleanup_webhook_events,
) -> None:
    delivery_id = _delivery("malformed")
    cleanup_webhook_events.append(delivery_id)
    with Session(postgres_engine) as setup:
        event = _insert_event(
            setup,
            delivery_id=delivery_id,
        )
        event.payload = "{bad"
        event.updated_at = datetime.now(UTC) - timedelta(hours=1)
        setup.commit()

    service = WebhookRecoveryService(lambda: Session(postgres_engine), SimpleNamespace())
    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.failed == 1
    with Session(postgres_engine) as verify:
        event = verify.scalar(
            select(WebhookEvent).where(
                WebhookEvent.delivery_id == delivery_id
            )
        )
        assert event is not None
        assert event.status == "received"
        assert event.attempt_count == 1
