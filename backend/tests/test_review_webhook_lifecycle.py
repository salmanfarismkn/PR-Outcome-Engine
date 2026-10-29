from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call
import hashlib
import hmac

import app.main  # noqa: F401
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.application import review_webhook
from app.application.review_webhook import ReviewWebhookService
from app.application.webhook_retry import WebhookRetryService
from app.webhook.router import github_webhook
from app.webhook.exceptions import WebhookDependencyPending
from app.webhook.schemas import PullRequestReviewWebhookPayload
from app.webhook.service import WebhookService


def _payload() -> PullRequestReviewWebhookPayload:
    return PullRequestReviewWebhookPayload.model_validate(
        {
            "action": "submitted",
            "repository": {
                "id": 700,
                "name": "event-checker",
                "full_name": "azuzm/event-checker",
                "owner": {"login": "azuzm"},
            },
            "pull_request": {
                "id": 501,
                "number": 167,
                "title": "Dataset sample",
                "state": "open",
                "merged": False,
                "merged_at": None,
                "closed_at": None,
            },
            "review": {
                "id": 801,
                "user": {"id": 90, "login": "reviewer"},
                "state": "APPROVED",
                "body": "Looks good",
                "submitted_at": "2026-10-12T06:00:00Z",
                "html_url": "https://example.test/review/801",
            },
        }
    )


def test_review_payload_persists_approval_before_snapshot_and_outcome(
    monkeypatch,
) -> None:
    calls = []
    pull_request = SimpleNamespace(
        id=177,
        github_id=501,
        merged=False,
        state="open",
    )
    repository = SimpleNamespace(id=70)
    db = Mock()
    db.scalar.side_effect = [repository, pull_request, None]
    db.commit.side_effect = lambda: calls.append("review_commit")

    service = ReviewWebhookService()
    service._feature_service = Mock(
        create_snapshot=lambda **_: calls.append("snapshot")
    )

    monkeypatch.setattr(
        review_webhook,
        "evaluate_pull_request_outcome",
        lambda **_: calls.append("outcome"),
    )
    review = service.process(db, _payload())

    assert calls == ["review_commit", "snapshot", "outcome"]
    db.refresh.assert_called_once()
    assert review.github_id == 801
    assert review.pull_request_id == 177
    assert review.reviewer_login == "reviewer"
    assert review.state == "APPROVED"


def test_duplicate_review_delivery_updates_existing_record_once(
    monkeypatch,
) -> None:
    pull_request = SimpleNamespace(id=177, merged=False, state="open")
    existing_review = SimpleNamespace(
        github_id=801,
        pull_request_id=177,
        reviewer_login="reviewer",
        state="COMMENTED",
        body="Earlier state",
        submitted_at=None,
    )
    db = Mock()
    repository = SimpleNamespace(id=70)
    db.scalar.side_effect = [
        repository,
        pull_request,
        existing_review,
        repository,
        pull_request,
        existing_review,
    ]
    feature_service = Mock()
    service = ReviewWebhookService()
    service._feature_service = feature_service
    monkeypatch.setattr(
        review_webhook,
        "evaluate_pull_request_outcome",
        Mock(),
    )

    first = service.process(db, _payload())
    second = service.process(db, _payload())

    assert first is existing_review
    assert second is existing_review
    assert existing_review.state == "APPROVED"
    assert db.add.call_count == 0
    assert db.commit.call_count == 2
    assert feature_service.create_snapshot.call_count == 2


def test_review_for_non_open_pr_does_not_refresh_snapshot(monkeypatch) -> None:
    pull_request = SimpleNamespace(id=177, merged=True, state="closed")
    repository = SimpleNamespace(id=70)
    db = Mock()
    db.scalar.side_effect = [repository, pull_request, None]
    feature_service = Mock()
    service = ReviewWebhookService()
    service._feature_service = feature_service
    monkeypatch.setattr(
        review_webhook,
        "evaluate_pull_request_outcome",
        Mock(),
    )

    service.process(db, _payload())

    feature_service.create_snapshot.assert_not_called()


def test_webhook_signature_uses_sha256_hmac() -> None:
    payload = b'{"action":"submitted"}'
    secret = "test-secret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    assert WebhookService.verify_signature(
        payload,
        f"sha256={digest}",
        secret,
    )
    assert not WebhookService.verify_signature(
        payload,
        "sha256=invalid",
        secret,
    )
    assert not WebhookService.verify_signature(
        payload,
        f"sha256={digest}",
        "",
    )


def test_review_webhook_defers_when_pr_has_not_been_ingested() -> None:
    db = Mock()
    db.scalar.side_effect = [SimpleNamespace(id=70), None]

    with pytest.raises(WebhookDependencyPending):
        ReviewWebhookService().process(db, _payload())


def test_review_webhook_defers_when_repository_has_not_been_ingested() -> None:
    db = Mock()
    db.scalar.return_value = None

    with pytest.raises(
        WebhookDependencyPending,
        match="Repository from review webhook",
    ):
        ReviewWebhookService().process(db, _payload())


def test_pending_review_delivery_replays_when_matching_pr_is_ingested() -> None:
    matching = SimpleNamespace(
        delivery_id="review-delivery",
        payload=_payload().model_dump_json(),
    )
    unrelated_payload = _payload().model_copy(
        update={
            "pull_request": _payload().pull_request.model_copy(
                update={"id": 999}
            )
        }
    )
    unrelated = SimpleNamespace(
        delivery_id="unrelated-delivery",
        payload=unrelated_payload.model_dump_json(),
    )
    pull_request = SimpleNamespace(
        github_id=501,
        repository=SimpleNamespace(github_id=700),
    )
    db = Mock()
    db.scalars.return_value = [matching, unrelated]
    service = WebhookRetryService()
    service._review_service = Mock()
    service._webhook_service = Mock()

    processed = service.retry_pending_review_events(db, pull_request)

    assert processed == 1
    service._review_service.process.assert_called_once()
    service._webhook_service.mark_processing.assert_called_once_with(
        db,
        matching,
    )
    service._webhook_service.mark_processed.assert_called_once_with(
        db,
        matching,
    )
    assert service._webhook_service.mark_processing.call_args_list == [
        call(db, matching)
    ]


def test_failed_review_replay_stays_pending_and_propagates() -> None:
    pending_event = SimpleNamespace(
        delivery_id="review-delivery",
        payload=_payload().model_dump_json(),
    )
    pull_request = SimpleNamespace(
        github_id=501,
        repository=SimpleNamespace(github_id=700),
    )
    db = Mock()
    db.scalars.return_value = [pending_event]
    service = WebhookRetryService()
    service._review_service = Mock(
        process=Mock(side_effect=RuntimeError("database unavailable"))
    )
    service._webhook_service = Mock()

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.retry_pending_review_events(db, pull_request)

    service._webhook_service.mark_pending.assert_called_once_with(
        db,
        pending_event,
        "database unavailable",
    )
    service._webhook_service.mark_failed.assert_not_called()
    service._webhook_service.mark_processed.assert_not_called()


@pytest.mark.asyncio
async def test_processed_review_delivery_is_idempotently_ignored(
    monkeypatch,
) -> None:
    payload = b'{"action":"submitted"}'
    request = SimpleNamespace(body=AsyncMock(return_value=payload))
    event = SimpleNamespace(status="processed")
    service = Mock()
    service.verify_signature.return_value = True
    service.get_event.return_value = event
    monkeypatch.setattr("app.webhook.router.webhook_service", service)
    monkeypatch.setattr(
        "app.webhook.router.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="test-secret"),
    )
    dispatcher = Mock()
    monkeypatch.setattr(
        "app.webhook.router.webhook_dispatcher",
        dispatcher,
    )

    result = await github_webhook(
        request=request,
        x_github_event="pull_request_review",
        x_github_delivery="delivery-1",
        x_hub_signature_256="sha256=valid",
        db=Mock(),
    )

    assert result == {"status": "already_processed"}
    service.verify_signature.assert_called_once_with(
        payload=payload,
        signature="sha256=valid",
        secret="test-secret",
    )
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_successfully_processed_delivery_returns_processed_status(
    monkeypatch,
) -> None:
    payload = _payload().model_dump_json().encode()
    request = SimpleNamespace(
        body=AsyncMock(return_value=payload),
        headers={"X-GitHub-Event": "pull_request_review"},
    )
    event = SimpleNamespace(status="received")
    service = Mock()
    service.verify_signature.return_value = True
    service.get_event.return_value = None
    service.create_event.return_value = event
    service.parse_payload.return_value = _payload().model_dump()
    monkeypatch.setattr("app.webhook.router.webhook_service", service)
    monkeypatch.setattr(
        "app.webhook.router.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="test-secret"),
    )
    dispatcher = Mock()
    monkeypatch.setattr("app.webhook.router.webhook_dispatcher", dispatcher)

    result = await github_webhook(
        request=request,
        x_github_event="pull_request_review",
        x_github_delivery="delivery-success",
        x_hub_signature_256="sha256=valid",
        db=Mock(),
    )

    assert result == {
        "status": "processed",
        "event": "pull_request_review",
    }
    service.mark_processing.assert_called_once()
    dispatcher.dispatch.assert_called_once()
    service.mark_processed.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_status_commit_fails", [False, True])
async def test_processed_status_commit_failure_returns_http_500(
    monkeypatch,
    failed_status_commit_fails: bool,
) -> None:
    payload = _payload().model_dump_json().encode()
    request = SimpleNamespace(body=AsyncMock(return_value=payload))
    event = SimpleNamespace(status="received", error_message=None)
    db = Mock()
    commit_error = IntegrityError(
        "UPDATE webhook_event",
        {},
        RuntimeError("commit rejected"),
    )
    db.commit.side_effect = [
        None,
        commit_error,
        commit_error if failed_status_commit_fails else None,
    ]
    service = WebhookService()
    service.verify_signature = Mock(return_value=True)
    service.get_event = Mock(return_value=None)
    service.create_event = Mock(return_value=event)
    service.parse_payload = Mock(return_value=_payload().model_dump())
    monkeypatch.setattr("app.webhook.router.webhook_service", service)
    monkeypatch.setattr(
        "app.webhook.router.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="test-secret"),
    )
    dispatcher = Mock()
    monkeypatch.setattr("app.webhook.router.webhook_dispatcher", dispatcher)

    with pytest.raises(HTTPException) as exc_info:
        await github_webhook(
            request=request,
            x_github_event="pull_request_review",
            x_github_delivery="delivery-commit-failure",
            x_hub_signature_256="sha256=valid",
            db=db,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Webhook processing failed."
    assert db.commit.call_count == 3
    assert db.rollback.call_count == 1 + failed_status_commit_fails
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_review_dependency_is_persisted_as_pending_delivery(
    monkeypatch,
) -> None:
    payload = _payload().model_dump_json().encode()
    event = SimpleNamespace(status="received")
    db = Mock()
    request = SimpleNamespace(body=AsyncMock(return_value=payload))
    service = Mock()
    service.verify_signature.return_value = True
    service.get_event.return_value = None
    service.create_event.return_value = event
    service.parse_payload.return_value = _payload().model_dump()
    monkeypatch.setattr("app.webhook.router.webhook_service", service)
    monkeypatch.setattr(
        "app.webhook.router.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="test-secret"),
    )
    dispatcher = Mock()
    dispatcher.dispatch.side_effect = WebhookDependencyPending(
        "PR has not been synchronized"
    )
    monkeypatch.setattr("app.webhook.router.webhook_dispatcher", dispatcher)

    result = await github_webhook(
        request=request,
        x_github_event="pull_request_review",
        x_github_delivery="delivery-pending",
        x_hub_signature_256="sha256=valid",
        db=db,
    )

    assert result == {
        "status": "pending",
        "reason": "PR has not been synchronized",
    }
    service.mark_pending.assert_called_once_with(
        db=db,
        event=event,
        reason="PR has not been synchronized",
    )


@pytest.mark.asyncio
async def test_review_delivery_with_invalid_signature_is_rejected(
    monkeypatch,
) -> None:
    payload = b'{"action":"submitted"}'
    request = SimpleNamespace(body=AsyncMock(return_value=payload))
    service = Mock()
    service.verify_signature.return_value = False
    monkeypatch.setattr("app.webhook.router.webhook_service", service)
    monkeypatch.setattr(
        "app.webhook.router.get_settings",
        lambda: SimpleNamespace(github_webhook_secret="test-secret"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await github_webhook(
            request=request,
            x_github_event="pull_request_review",
            x_github_delivery="delivery-invalid",
            x_hub_signature_256="sha256=invalid",
            db=Mock(),
        )

    assert exc_info.value.status_code == 401
    service.get_event.assert_not_called()
