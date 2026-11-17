from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.main  # noqa: F401
from app.application.webhook_recovery import (
    WebhookRecoveryService,
)
from app.webhook.models import WebhookEvent


def _event(
    *,
    status: str = "received",
    attempt_count: int = 0,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=11,
        delivery_id="delivery-recovery",
        event_type="pull_request_review",
        status=status,
        payload="{}",
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
        last_attempt_at=None,
        last_error_at=None,
        attempt_count=attempt_count,
        error_message=None,
    )


def test_dry_run_lists_stale_events_without_modifying_state() -> None:
    event = _event()
    db = Mock()
    db.scalars.return_value.all.return_value = [event]
    service = WebhookRecoveryService(Mock)

    candidates = service.list_stale_events(
        db,
        datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=10,
    )

    assert [candidate.delivery_id for candidate in candidates] == [
        "delivery-recovery"
    ]
    assert event.status == "received"
    assert event.attempt_count == 0
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


@pytest.mark.parametrize("status", ["received", "processing"])
def test_stale_statuses_are_selected_for_recovery(status: str) -> None:
    event = _event(status=status, attempt_count=1)
    db = Mock()
    db.scalar.return_value = event
    service = WebhookRecoveryService(Mock)

    candidate = service.claim_stale_event(
        db,
        datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
    )

    assert candidate is not None
    assert candidate.status == "processing"
    assert event.status == "processing"
    assert event.attempt_count == 2
    db.commit.assert_called_once()


def test_claim_uses_skip_locked_for_concurrent_workers() -> None:
    event = _event()
    db = Mock()
    db.scalar.return_value = event
    service = WebhookRecoveryService(Mock)

    service.claim_stale_event(
        db,
        datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
    )

    statement = db.scalar.call_args.args[0]
    assert statement._for_update_arg.skip_locked is True


def test_claim_database_failure_rolls_back() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    event = _event()
    db = Mock()
    db.scalar.return_value = event
    db.commit.side_effect = SQLAlchemyError("database unavailable")
    service = WebhookRecoveryService(Mock)

    with pytest.raises(SQLAlchemyError):
        service.claim_stale_event(
            db,
            datetime.now(UTC) - timedelta(minutes=15),
            max_attempts=3,
        )

    db.rollback.assert_called_once()


def test_no_stale_event_does_not_modify_database() -> None:
    db = Mock()
    db.scalar.return_value = None
    service = WebhookRecoveryService(Mock)

    assert (
        service.claim_stale_event(
            db,
            datetime.now(UTC) - timedelta(minutes=15),
            max_attempts=3,
        )
        is None
    )
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_stale_query_excludes_recent_processed_pending_and_exhausted_events() -> None:
    engine = create_engine("sqlite://")
    WebhookEvent.__table__.create(engine)
    now = datetime.now(UTC)

    def add_event(
        db: Session,
        event_id: int,
        status: str,
        created_at: datetime,
        attempt_count: int = 0,
    ) -> None:
        db.add(
            WebhookEvent(
                id=event_id,
                delivery_id=f"delivery-{event_id}",
                event_type="pull_request_review",
                status=status,
                payload="{}",
                created_at=created_at,
                updated_at=created_at,
                attempt_count=attempt_count,
            )
        )

    with Session(engine) as db:
        add_event(db, 1, "received", now - timedelta(hours=1))
        add_event(db, 2, "processing", now - timedelta(hours=1))
        add_event(db, 3, "received", now - timedelta(minutes=1))
        add_event(db, 4, "processed", now - timedelta(hours=1))
        add_event(db, 5, "pending", now - timedelta(hours=1))
        add_event(db, 6, "received", now - timedelta(hours=1), 3)
        db.commit()

        candidates = WebhookRecoveryService(Mock).list_stale_events(
            db,
            now - timedelta(minutes=15),
            max_attempts=3,
            limit=10,
        )

    assert {candidate.event_id for candidate in candidates} == {1, 2}


def test_operational_metrics_report_statuses_and_recovery_age() -> None:
    engine = create_engine("sqlite://")
    WebhookEvent.__table__.create(engine)
    now = datetime.now(UTC)

    with Session(engine) as db:
        for event_id, status, attempts, age in (
            (1, "received", 0, timedelta(hours=1)),
            (2, "processing", 1, timedelta(minutes=20)),
            (3, "pending", 0, timedelta(hours=1)),
            (4, "processed", 0, timedelta(hours=1)),
            (5, "failed", 3, timedelta(hours=1)),
        ):
            created_at = now - age
            db.add(
                WebhookEvent(
                    id=event_id,
                    delivery_id=f"metrics-{event_id}",
                    event_type="pull_request_review",
                    status=status,
                    payload="{}",
                    created_at=created_at,
                    updated_at=created_at,
                    attempt_count=attempts,
                )
            )
        db.commit()

        metrics = WebhookRecoveryService(Mock).get_operational_metrics(
            db,
            now - timedelta(minutes=15),
            max_attempts=3,
            recovery_attempts=2,
        )

    assert metrics.total == 5
    assert metrics.received == 1
    assert metrics.processing == 1
    assert metrics.pending == 1
    assert metrics.processed == 1
    assert metrics.failed == 1
    assert metrics.exhausted == 1
    assert metrics.eligible_for_recovery == 2
    assert metrics.oldest_unrecovered_age is not None
    assert metrics.recovery_attempts == 2


def test_status_logging_has_context_without_payload(caplog) -> None:
    event = _event()
    event.id = 11
    db = Mock()

    with caplog.at_level("INFO"):
        from app.webhook.service import WebhookService

        WebhookService().mark_processed(db, event)

    assert "event_id=11" in caplog.text
    assert "delivery_id=delivery-recovery" in caplog.text
    assert "payload" not in caplog.text


def test_recovery_dispatches_through_existing_dispatcher_and_processes() -> None:
    event = _event()
    dispatcher = Mock()

    class Session:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return event

        def commit(self):
            return None

        def get(self, _model, _event_id):
            return event

    sessions = iter([Session("claim"), Session("process")])
    service = WebhookRecoveryService(lambda: next(sessions), dispatcher)

    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.recovered == 1
    assert event.status == "processed"
    dispatcher.dispatch.assert_called_once()
    assert dispatcher.dispatch.call_args.kwargs["event_type"] == (
        "pull_request_review"
    )
    assert dispatcher.dispatch.call_args.kwargs["payload"] == {}
    assert dispatcher.dispatch.call_args.kwargs["delivery_id"] == (
        "delivery-recovery"
    )


def test_handler_failure_is_retryable_until_limit_then_failed() -> None:
    event = _event(attempt_count=2)
    dispatcher = Mock()
    dispatcher.dispatch.side_effect = RuntimeError("handler failed")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return event

        def commit(self):
            return None

        def get(self, _model, _event_id):
            return event

        def rollback(self):
            return None

    sessions = iter([Session(), Session()])
    service = WebhookRecoveryService(lambda: next(sessions), dispatcher)

    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.failed == 1
    assert event.status == "failed"
    assert event.error_message == "handler failed"
    assert event.last_error_at is not None


def test_handler_failure_before_limit_returns_event_to_received() -> None:
    event = _event(attempt_count=0)
    dispatcher = Mock()
    dispatcher.dispatch.side_effect = RuntimeError("temporary failure")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return event

        def commit(self):
            return None

        def get(self, _model, _event_id):
            return event

    sessions = iter([Session(), Session()])
    service = WebhookRecoveryService(lambda: next(sessions), dispatcher)

    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.failed == 1
    assert event.status == "received"
    assert event.error_message == "temporary failure"


def test_malformed_payload_is_recorded_as_retryable_failure() -> None:
    event = _event()
    event.payload = "{not-json"
    dispatcher = Mock()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return event

        def commit(self):
            return None

        def get(self, _model, _event_id):
            return event

    sessions = iter([Session(), Session()])
    service = WebhookRecoveryService(lambda: next(sessions), dispatcher)

    summary = service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    assert summary.failed == 1
    assert event.status == "received"
    assert "Expecting property name" in event.error_message
    dispatcher.dispatch.assert_not_called()


def test_recovery_uses_dispatcher_not_direct_handler() -> None:
    event = _event()
    dispatcher = Mock()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return event

        def commit(self):
            return None

        def get(self, _model, _event_id):
            return event

    service = WebhookRecoveryService(lambda: Session(), dispatcher)

    service.recover(
        stale_before=datetime.now(UTC) - timedelta(minutes=15),
        max_attempts=3,
        limit=1,
    )

    dispatcher.dispatch.assert_called_once()
