from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from app.application import review_webhook
from app.application.review_webhook import ReviewWebhookService


def test_review_is_persisted_before_snapshot_and_outcome(monkeypatch) -> None:
    calls = []
    pull_request = SimpleNamespace(id=174, merged=False, state="open")
    review = SimpleNamespace(
        id=801,
        user=SimpleNamespace(login="reviewer"),
        state="APPROVED",
        body="Looks good",
        submitted_at=datetime.now(timezone.utc),
        html_url="https://example.test/review/801",
    )
    payload = SimpleNamespace(
        action="submitted",
        pull_request=SimpleNamespace(id=501),
        review=review,
    )
    db = Mock()
    db.scalar.side_effect = [pull_request, None]
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
    service.process(db, payload)

    assert calls == ["review_commit", "snapshot", "outcome"]
    db.refresh.assert_called_once()
