from types import SimpleNamespace
from unittest.mock import Mock

# Import the application first to initialize the ORM models in their
# existing dependency order.
import app.main  # noqa: F401

from app.application import check_sync
from app.check.schemas import CheckRunImportSummary


def test_import_check_runs_uses_pull_request_head_sha(monkeypatch) -> None:
    db = object()
    pull_request = SimpleNamespace(
        id=174,
        number=164,
        repository=SimpleNamespace(
            owner="azuzm",
            name="event-checker",
        ),
    )
    github_pull_request = SimpleNamespace(
        head=SimpleNamespace(sha="head-commit-sha"),
    )
    check_runs = [object()]
    summary = CheckRunImportSummary(
        imported=1,
        skipped=0,
        total=1,
    )

    github = Mock()
    github.get_pull_request.return_value = github_pull_request
    github.list_check_runs.return_value = check_runs
    check_service = Mock()
    check_service.import_check_runs.return_value = summary

    monkeypatch.setattr(
        check_sync,
        "GitHubService",
        lambda: github,
    )
    monkeypatch.setattr(
        check_sync,
        "CheckRunService",
        lambda: check_service,
    )

    result = check_sync.CheckSyncService().import_check_runs(
        db=db,
        pull_request=pull_request,
    )

    github.get_pull_request.assert_called_once_with(
        owner="azuzm",
        repository="event-checker",
        pull_number=164,
    )
    github.list_check_runs.assert_called_once_with(
        owner="azuzm",
        repository="event-checker",
        ref="head-commit-sha",
    )
    check_service.import_check_runs.assert_called_once_with(
        db=db,
        pull_request_id=174,
        check_runs=check_runs,
    )
    assert result == summary
