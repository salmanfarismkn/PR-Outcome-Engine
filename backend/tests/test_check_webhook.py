from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.main  # noqa: F401
from app.application import check_webhook
from app.webhook.exceptions import WebhookDependencyPending
from app.webhook.schemas import CheckRunWebhookPayload


def _payload() -> CheckRunWebhookPayload:
    return CheckRunWebhookPayload.model_validate(
        {
            "action": "completed",
            "repository": {
                "id": 10,
                "name": "repo",
                "full_name": "owner/repo",
                "owner": {"login": "owner"},
            },
            "check_run": {
                "id": 501,
                "name": "tests",
                "status": "completed",
                "conclusion": "failure",
                "details_url": None,
                "started_at": None,
                "completed_at": None,
                "head_sha": "head-sha",
                "pull_requests": [{"number": 12}],
            },
        }
    )


def test_check_webhook_syncs_only_pull_requests_associated_with_repo(
    monkeypatch,
) -> None:
    calls = []
    pull_request = SimpleNamespace(id=174, number=12)
    repository = SimpleNamespace(id=10)
    check_run = SimpleNamespace(github_id=501, pull_request_id=174)
    sync = Mock()
    sync.import_check_runs.side_effect = (
        lambda **_: calls.append("checks")
    )
    features = Mock()
    features.create_snapshot.side_effect = (
        lambda **_: calls.append("snapshot")
    )
    monkeypatch.setattr(
        check_webhook,
        "CheckSyncService",
        lambda: sync,
    )
    monkeypatch.setattr(
        check_webhook,
        "PRFeatureService",
        lambda: features,
    )
    outcome_evaluation = Mock(
        side_effect=lambda **_: calls.append("outcome")
    )
    monkeypatch.setattr(
        check_webhook,
        "evaluate_pull_request_outcome",
        outcome_evaluation,
    )
    db = Mock()
    db.scalar.side_effect = [repository, check_run]
    db.scalars.return_value.all.return_value = [pull_request]

    result = check_webhook.CheckRunWebhookService().process(
        db,
        _payload(),
    )

    assert result == [check_run]
    assert calls == ["checks", "snapshot", "outcome"]
    sync.import_check_runs.assert_called_once_with(
        db=db,
        pull_request=pull_request,
    )
    features.create_snapshot.assert_called_once_with(
        db=db,
        pull_request=pull_request,
    )
    outcome_evaluation.assert_called_once_with(
        db=db,
        pull_request_id=174,
    )


def test_check_webhook_ignores_unassociated_check() -> None:
    db = Mock()
    db.scalar.return_value = SimpleNamespace(id=10)
    db.scalars.return_value.all.return_value = []
    payload = _payload()
    payload.check_run.pull_requests = []

    assert check_webhook.CheckRunWebhookService().process(
        db,
        payload,
    ) == []


def test_check_webhook_defers_when_associated_pr_is_not_ingested(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        check_webhook,
        "CheckSyncService",
        lambda: Mock(),
    )
    db = Mock()
    db.scalar.return_value = SimpleNamespace(id=10)
    db.scalars.return_value.all.return_value = []

    with pytest.raises(WebhookDependencyPending):
        check_webhook.CheckRunWebhookService().process(
            db,
            _payload(),
        )
