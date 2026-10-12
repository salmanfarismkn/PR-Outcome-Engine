from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

import app.main  # noqa: F401
from app.application import review_sync
from app.application.review_sync import ReviewSyncService
from app.github.schemas import GitHubReview, GitHubReviewUser
from app.review.service import ReviewService


def _github_review(
    *,
    review_id: int = 801,
    state: str = "COMMENTED",
    body: str | None = "Review body",
    submitted_at: datetime | None = None,
    user: GitHubReviewUser | None = None,
) -> GitHubReview:
    return GitHubReview(
        id=review_id,
        user=user or GitHubReviewUser(login="reviewer"),
        state=state,
        body=body,
        submitted_at=submitted_at
        or datetime(2026, 10, 12, tzinfo=timezone.utc),
    )


def _mock_db(existing_reviews: list[object] | None = None) -> Mock:
    records = list(existing_reviews or [])
    db = Mock()
    db.scalars.return_value.all.side_effect = lambda: list(records)
    db.add.side_effect = records.append
    return db


def test_import_reviews_inserts_new_review() -> None:
    db = _mock_db()

    result = ReviewService().import_reviews(
        db,
        pull_request_id=181,
        reviews=[_github_review()],
    )

    assert result.imported == 1
    assert result.updated == 0
    assert result.skipped == 0
    assert result.total == 1
    inserted = db.add.call_args.args[0]
    assert inserted.github_id == 801
    assert inserted.pull_request_id == 181
    assert inserted.state == "COMMENTED"
    assert inserted.reviewer_login == "reviewer"
    db.commit.assert_called_once()


def test_import_reviews_updates_existing_approval_and_timestamps() -> None:
    old_timestamp = datetime(2026, 10, 11, tzinfo=timezone.utc)
    new_timestamp = datetime(2026, 10, 12, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        github_id=801,
        pull_request_id=181,
        reviewer_login="reviewer",
        state="CHANGES_REQUESTED",
        body="Please fix",
        submitted_at=old_timestamp,
    )
    db = _mock_db([existing])

    result = ReviewService().import_reviews(
        db,
        pull_request_id=181,
        reviews=[
            _github_review(
                state="APPROVED",
                body="Approved",
                submitted_at=new_timestamp,
            )
        ],
    )

    assert result.imported == 0
    assert result.updated == 1
    assert result.skipped == 0
    assert existing.state == "APPROVED"
    assert existing.body == "Approved"
    assert existing.submitted_at == new_timestamp
    db.add.assert_not_called()
    db.commit.assert_called_once()


def test_reimporting_identical_review_is_a_noop() -> None:
    existing = SimpleNamespace(
        github_id=801,
        pull_request_id=181,
        reviewer_login="reviewer",
        state="APPROVED",
        body="Approved",
        submitted_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    db = _mock_db([existing])
    review = _github_review(state="APPROVED", body="Approved")

    result = ReviewService().import_reviews(
        db,
        pull_request_id=181,
        reviews=[review, review],
    )

    assert result.imported == 0
    assert result.updated == 0
    assert result.skipped == 2
    assert result.total == 2
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_review_id_associated_with_another_pr_is_rejected_without_changes() -> None:
    existing = SimpleNamespace(
        github_id=801,
        pull_request_id=999,
        reviewer_login="reviewer",
        state="COMMENTED",
        body="Existing",
        submitted_at=None,
    )
    db = _mock_db([existing])

    with pytest.raises(ValueError, match="already associated"):
        ReviewService().import_reviews(
            db,
            pull_request_id=181,
            reviews=[
                _github_review(state="APPROVED"),
                _github_review(review_id=802, state="APPROVED"),
            ],
        )

    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_empty_review_sync_is_a_noop(monkeypatch) -> None:
    github = Mock()
    github.list_reviews.return_value = []
    monkeypatch.setattr(review_sync, "GitHubService", lambda: github)
    pull_request = SimpleNamespace(
        id=181,
        number=171,
        repository=SimpleNamespace(owner="azuzm", name="event-checker"),
    )
    db = _mock_db()

    result = ReviewSyncService().import_reviews(db, pull_request)

    assert result.total == 0
    assert result.imported == result.updated == result.skipped == 0
    github.list_reviews.assert_called_once_with(
        owner="azuzm",
        repository="event-checker",
        pull_number=171,
    )
    db.scalars.assert_not_called()
    db.commit.assert_not_called()


def test_review_sync_propagates_github_api_errors(monkeypatch) -> None:
    response = httpx.Response(
        503,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/azuzm/event-checker/pulls/171/reviews",
        ),
    )
    github = Mock()
    github.list_reviews.side_effect = httpx.HTTPStatusError(
        "GitHub unavailable",
        request=response.request,
        response=response,
    )
    monkeypatch.setattr(review_sync, "GitHubService", lambda: github)
    db = _mock_db()
    pull_request = SimpleNamespace(
        id=181,
        number=171,
        repository=SimpleNamespace(owner="azuzm", name="event-checker"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        ReviewSyncService().import_reviews(db, pull_request)

    db.scalars.assert_not_called()
    db.commit.assert_not_called()
