from types import SimpleNamespace
from unittest.mock import Mock

import app.main  # noqa: F401
from app.check.schemas import CheckRunImportSummary
from app.check.service import CheckRunService


def test_check_import_updates_existing_run_and_is_idempotent() -> None:
    db = Mock()
    existing = SimpleNamespace(
        github_id=501,
        pull_request_id=174,
        head_sha="old-head",
        name="tests",
        status="in_progress",
        conclusion=None,
        details_url=None,
        started_at=None,
        completed_at=None,
    )
    db.scalars.return_value.all.return_value = [existing]
    check = SimpleNamespace(
        id=501,
        head_sha="new-head",
        name="tests",
        status="completed",
        conclusion="success",
        details_url="https://example.test/check/501",
        started_at=None,
        completed_at=None,
    )
    service = CheckRunService()

    updated = service.import_check_runs(db, 174, [check])
    assert updated == CheckRunImportSummary(
        imported=0,
        skipped=0,
        total=1,
        updated=1,
    )
    assert existing.status == "completed"
    assert existing.conclusion == "success"
    assert existing.head_sha == "new-head"

    unchanged = service.import_check_runs(db, 174, [check])
    assert unchanged.updated == 0
    assert unchanged.skipped == 1
    db.add.assert_not_called()


def test_import_does_not_reassign_globally_unique_check_to_another_pr() -> None:
    db = Mock()
    existing = SimpleNamespace(
        github_id=502,
        pull_request_id=99,
        head_sha="same-sha",
    )
    db.scalars.return_value.all.return_value = [existing]
    check = SimpleNamespace(
        id=502,
        head_sha="same-sha",
        name="tests",
        status="completed",
        conclusion="failure",
        details_url=None,
        started_at=None,
        completed_at=None,
    )

    summary = CheckRunService().import_check_runs(db, 174, [check])

    assert summary.imported == 0
    assert summary.updated == 0
    assert summary.skipped == 1
    assert existing.pull_request_id == 99
    db.add.assert_not_called()
