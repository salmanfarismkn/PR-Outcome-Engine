from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from app.dataset.service import TrainingDatasetService
from app.feature.models import PRFeatureSnapshot
from app.outcome.models import PullRequestOutcome


def _snapshot(created_at: datetime, additions: int) -> SimpleNamespace:
    return SimpleNamespace(
        pull_request_id=174,
        additions=additions,
        deletions=1,
        changed_files=2,
        commit_count=2,
        unique_authors=1,
        review_count=1,
        unique_reviewers=1,
        approvals=1,
        change_requests=0,
        is_draft=False,
        age_hours=3.0,
        created_at=created_at,
    )


def test_training_uses_latest_premerge_snapshot_once_per_pr() -> None:
    merged_at = datetime.now(timezone.utc)
    outcome = SimpleNamespace(
        pull_request_id=174,
        outcome="healthy",
        merged_at=merged_at,
        observed_at=merged_at + timedelta(days=1),
    )
    duplicate_outcome = SimpleNamespace(
        pull_request_id=174,
        outcome="problematic",
        merged_at=merged_at,
        observed_at=merged_at,
    )
    missing_merge_time = SimpleNamespace(
        pull_request_id=175,
        outcome="healthy",
        merged_at=None,
        observed_at=merged_at,
    )
    outcomes_query = Mock()
    outcomes_query.filter.return_value.all.return_value = [
        outcome,
        duplicate_outcome,
        missing_merge_time,
    ]
    snapshots_query = Mock()
    snapshots_query.filter.return_value.order_by.return_value.all.return_value = [
        _snapshot(merged_at + timedelta(seconds=1), additions=99),
        _snapshot(merged_at - timedelta(seconds=1), additions=7),
        _snapshot(merged_at - timedelta(days=1), additions=3),
    ]
    db = Mock()
    db.query.side_effect = {
        PullRequestOutcome: outcomes_query,
        PRFeatureSnapshot: snapshots_query,
    }.get

    dataset = TrainingDatasetService().build_dataset(db)

    assert len(dataset) == 1
    assert dataset[0]["pull_request_id"] == 174
    assert dataset[0]["additions"] == 7
    assert dataset[0]["label"] == "healthy"
