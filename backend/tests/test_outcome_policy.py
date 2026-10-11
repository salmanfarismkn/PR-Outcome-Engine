from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.main  # noqa: F401
from app.check.models import CheckRun
from app.outcome.models import PullRequestOutcome
from app.outcome.revert_models import RevertEvent
from app.outcome.service import OutcomeEvaluator


@pytest.mark.parametrize(
    ("merged", "checks", "has_revert", "expected", "reason"),
    [
        (True, [], False, "uncertain", "No CI evidence"),
        (
            True,
            [
                SimpleNamespace(
                    head_sha="current",
                    status="completed",
                    conclusion="success",
                )
            ],
            False,
            "healthy",
            "completed successful CI",
        ),
        (
            True,
            [
                SimpleNamespace(
                    head_sha="current",
                    status="completed",
                    conclusion="success",
                ),
                SimpleNamespace(
                    head_sha="old",
                    status="completed",
                    conclusion="failure",
                ),
            ],
            False,
            "healthy",
            "completed successful CI",
        ),
        (
            True,
            [
                SimpleNamespace(
                    head_sha="current",
                    status="completed",
                    conclusion="failure",
                )
            ],
            False,
            "problematic",
            "completed failing CI",
        ),
        (
            True,
            [
                SimpleNamespace(
                    head_sha="current",
                    status="in_progress",
                    conclusion=None,
                )
            ],
            False,
            "uncertain",
            "exclusively completed successful",
        ),
        (False, [], False, "uncertain", "not been merged"),
        (True, [], True, "problematic", "later reverted"),
    ],
)
def test_outcome_policy_is_conservative_and_repeatable(
    merged,
    checks,
    has_revert,
    expected,
    reason,
) -> None:
    outcome = SimpleNamespace(
        lifecycle_status=None,
        outcome=None,
        reason=None,
        merged_at=datetime.now(timezone.utc),
        observed_at=None,
    )
    outcome_query = Mock()
    outcome_query.filter.return_value.first.return_value = outcome
    checks_query = Mock()
    checks_query.filter.return_value.all.return_value = checks
    revert_query = Mock()
    revert_query.filter.return_value.first.return_value = (
        object() if has_revert else None
    )
    db = Mock()
    db.query.side_effect = {
        PullRequestOutcome: outcome_query,
        CheckRun: checks_query,
        RevertEvent: revert_query,
    }.get
    pull_request = SimpleNamespace(
        id=174,
        merged=merged,
        merged_at=outcome.merged_at if merged else None,
        state="closed" if merged else "open",
        head_sha="current",
    )

    result = OutcomeEvaluator().evaluate(db, pull_request)

    assert result is outcome
    assert result.outcome == expected
    assert reason in result.reason
    db.add.assert_called_once_with(outcome)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(outcome)
