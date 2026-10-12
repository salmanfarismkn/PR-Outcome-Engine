from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from scripts import backfill_check_runs


def test_backfill_syncs_pr_sources_before_snapshot_and_outcome(
    monkeypatch,
) -> None:
    calls = []
    db = Mock()
    pull_request = SimpleNamespace(id=174, merged=False)
    summary = SimpleNamespace(imported=1, updated=0, skipped=0)
    outcome = SimpleNamespace(outcome="healthy")

    pull_request_sync = Mock()
    pull_request_sync.sync_pull_request.side_effect = (
        lambda **kwargs: calls.append("pull_request_sources")
    )
    check_sync = Mock()
    check_sync.import_check_runs.side_effect = (
        lambda **kwargs: calls.append("check_runs") or summary
    )
    feature_service = Mock()
    feature_service.create_snapshot.side_effect = (
        lambda **kwargs: calls.append("snapshot")
    )

    class FakeOutcomeEvaluator:
        def evaluate(self, **kwargs):
            calls.append("outcome")
            return outcome

    monkeypatch.setattr(
        backfill_check_runs,
        "OutcomeEvaluator",
        FakeOutcomeEvaluator,
    )

    result, evaluated_outcome = backfill_check_runs.backfill_pull_request(
        db=db,
        pull_request=pull_request,
        pull_request_sync=pull_request_sync,
        check_sync=check_sync,
        feature_service=feature_service,
    )

    assert result is summary
    assert evaluated_outcome is outcome
    assert calls == [
        "pull_request_sources",
        "check_runs",
        "snapshot",
        "outcome",
    ]
    db.refresh.assert_called_once_with(pull_request)


def test_backfill_evaluates_merged_pr_without_snapshot(monkeypatch) -> None:
    calls = []
    db = Mock()
    pull_request = SimpleNamespace(id=174, merged=True)
    summary = SimpleNamespace(imported=0, updated=1, skipped=0)
    outcome = SimpleNamespace(outcome="healthy")
    pull_request_sync = Mock()
    pull_request_sync.sync_pull_request.side_effect = (
        lambda **kwargs: calls.append("pull_request_sources")
    )
    check_sync = Mock()
    check_sync.import_check_runs.side_effect = (
        lambda **kwargs: calls.append("check_runs") or summary
    )
    feature_service = Mock()
    feature_service.create_snapshot.side_effect = (
        lambda **kwargs: calls.append("snapshot")
    )

    class FakeOutcomeEvaluator:
        def evaluate(self, **kwargs):
            calls.append("outcome")
            return outcome

    monkeypatch.setattr(
        backfill_check_runs,
        "OutcomeEvaluator",
        FakeOutcomeEvaluator,
    )

    result, evaluated_outcome = backfill_check_runs.backfill_pull_request(
        db=db,
        pull_request=pull_request,
        pull_request_sync=pull_request_sync,
        check_sync=check_sync,
        feature_service=feature_service,
    )

    assert result is summary
    assert evaluated_outcome is outcome
    assert calls == ["pull_request_sources", "check_runs", "outcome"]
