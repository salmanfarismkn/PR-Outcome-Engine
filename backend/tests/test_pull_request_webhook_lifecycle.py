from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from app.application import pull_request_webhook


def _payload(action: str, *, merged: bool = False) -> SimpleNamespace:
    timestamp = datetime.now(timezone.utc) if merged else None
    return SimpleNamespace(
        action=action,
        repository=SimpleNamespace(
            owner={"login": "owner"},
            name="repo",
        ),
        pull_request=SimpleNamespace(
            id=501,
            number=12,
            title="test PR",
            author="author",
            base_branch="main",
            head_branch="feature",
            is_draft=False,
            state="closed" if merged else "open",
            merged=merged,
            merged_at=timestamp,
            closed_at=timestamp,
        ),
    )


def _service(monkeypatch, calls: list[str]):
    repository = SimpleNamespace(id=10)
    pull_request = SimpleNamespace(id=174)
    db = Mock()
    db.scalar.side_effect = [repository, pull_request]
    db.commit.side_effect = lambda: calls.append("initial_commit")
    db.refresh.side_effect = lambda _: calls.append("initial_refresh")

    monkeypatch.setattr(
        pull_request_webhook.PullRequestWebhookService,
        "_update_pull_request",
        staticmethod(lambda **_: calls.append("update")),
    )
    service = pull_request_webhook.PullRequestWebhookService()
    service._sync_service = Mock(
        sync_pull_request=lambda **_: calls.append("source_sync")
    )
    service._check_sync_service = Mock(
        import_check_runs=lambda **_: calls.append("check_sync")
    )
    service._review_sync_service = Mock(
        import_reviews=lambda **_: calls.append("review_sync")
    )
    service._feature_service = Mock(
        create_snapshot=lambda **_: calls.append("snapshot")
    )
    monkeypatch.setattr(
        pull_request_webhook,
        "evaluate_pull_request_outcome",
        lambda **_: calls.append("outcome"),
    )
    return service, db


def test_opened_pr_syncs_sources_and_evidence_before_snapshot_and_outcome(
    monkeypatch,
) -> None:
    calls: list[str] = []
    service, db = _service(monkeypatch, calls)

    service.process(db, _payload("opened"))

    assert calls.index("source_sync") < calls.index("check_sync")
    assert calls.index("source_sync") < calls.index("review_sync")
    assert calls.index("check_sync") < calls.index("snapshot")
    assert calls.index("review_sync") < calls.index("snapshot")
    assert calls.index("snapshot") < calls.index("outcome")


def test_merged_closed_pr_evaluates_evidence_without_creating_snapshot(
    monkeypatch,
) -> None:
    calls: list[str] = []
    service, db = _service(monkeypatch, calls)

    service.process(db, _payload("closed", merged=True))

    assert "check_sync" in calls
    assert "review_sync" in calls
    assert "outcome" in calls
    assert "source_sync" not in calls
    assert "snapshot" not in calls

