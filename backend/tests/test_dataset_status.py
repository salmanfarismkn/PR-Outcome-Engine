from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from app.dataset.router import get_pr_dataset_status


def test_dataset_status_counts_only_checks_for_current_head() -> None:
    pull_request = SimpleNamespace(
        id=177,
        github_id=4825671124,
        number=167,
        merged=False,
        state="open",
        head_sha="current-sha",
    )
    snapshot = SimpleNamespace()
    outcome = SimpleNamespace(
        lifecycle_status="open",
        outcome="uncertain",
    )
    db = Mock()
    db.scalar.side_effect = [pull_request, snapshot, outcome]
    db.scalars.return_value.all.return_value = [
        SimpleNamespace(
            head_sha="current-sha",
            status="completed",
            conclusion="success",
        ),
        SimpleNamespace(
            head_sha="old-sha",
            status="completed",
            conclusion="failure",
        ),
    ]

    status = get_pr_dataset_status(
        "azuzm",
        "event-checker",
        167,
        db,
    )

    assert status["head_sha"] == "current-sha"
    assert status["check_count"] == 1
    assert status["successful_checks"] == 1
    assert status["failed_checks"] == 0
    assert status["pending_checks"] == 0
