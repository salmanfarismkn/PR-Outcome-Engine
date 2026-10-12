from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
import pytest
from app.feature.service import PRFeatureService


def test_snapshot_counts_reviews_and_only_current_head_checks() -> None:
    db = Mock()
    db.scalars.side_effect = [
        iter([SimpleNamespace(author_name="alice")]),
        iter(
            [
                SimpleNamespace(reviewer_login="bob", state="APPROVED"),
                SimpleNamespace(
                    reviewer_login="carol",
                    state="CHANGES_REQUESTED",
                ),
            ]
        ),
        iter(
            [
                SimpleNamespace(
                    head_sha="current",
                    conclusion="success",
                    status="completed",
                ),
                SimpleNamespace(
                    head_sha="old",
                    conclusion="failure",
                    status="completed",
                ),
            ]
        ),
        iter(
            [
                SimpleNamespace(additions=4, deletions=2),
                SimpleNamespace(additions=3, deletions=0),
            ]
        ),
    ]
    pull_request = SimpleNamespace(
        id=174,
        head_sha="current",
        created_at=datetime.now(timezone.utc),
        is_draft=True,
    )

    snapshot = PRFeatureService().build_snapshot(db, pull_request)

    assert snapshot.review_count == 2
    assert snapshot.unique_reviewers == 2
    assert snapshot.approvals == 1
    assert snapshot.change_requests == 1
    assert snapshot.check_count == 1
    assert snapshot.successful_checks == 1
    assert snapshot.failed_checks == 0
    assert snapshot.additions == 7
    assert snapshot.deletions == 2
    assert snapshot.changed_files == 2
    assert snapshot.is_draft is True


@pytest.mark.parametrize(
    ("merged", "state"),
    [(True, "closed"), (False, "closed")],
)
def test_create_snapshot_skips_non_open_pull_request(
    merged: bool,
    state: str,
) -> None:
    db = Mock()
    pull_request = SimpleNamespace(
        id=174,
        merged=merged,
        state=state,
    )
    service = PRFeatureService()
    service.build_snapshot = Mock()

    assert service.create_snapshot(db, pull_request) is None

    service.build_snapshot.assert_not_called()
    db.add.assert_not_called()


def test_create_snapshot_skips_incomplete_source_data() -> None:
    db = Mock()
    pull_request = SimpleNamespace(
        id=174,
        merged=False,
        state="open",
    )
    service = PRFeatureService()
    service.build_snapshot = Mock(
        return_value=SimpleNamespace(
            pull_request_id=174,
            commit_count=0,
            changed_files=3,
        )
    )

    assert service.create_snapshot(db, pull_request) is None

    db.scalar.assert_not_called()
    db.add.assert_not_called()


def test_save_snapshot_reuses_identical_snapshot_without_mutating_timestamp() -> None:
    created_at = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
    values = {
        "pull_request_id": 174,
        "additions": 4,
        "deletions": 2,
        "changed_files": 2,
        "commit_count": 2,
        "unique_authors": 1,
        "review_count": 1,
        "unique_reviewers": 1,
        "approvals": 1,
        "change_requests": 0,
        "check_count": 1,
        "successful_checks": 1,
        "failed_checks": 0,
        "pending_checks": 0,
        "is_draft": False,
        "age_hours": 3.0,
    }
    existing = SimpleNamespace(
        id=99,
        created_at=created_at,
        **values,
    )
    snapshot = SimpleNamespace(
        created_at=created_at,
        **values,
    )
    db = Mock()
    db.scalar.return_value = existing

    saved = PRFeatureService().save_snapshot(db, snapshot)

    assert saved is existing
    assert saved.created_at == created_at
    db.add.assert_not_called()
    db.commit.assert_not_called()
