from types import SimpleNamespace
from unittest.mock import Mock

# Import the application first to initialize the ORM models in their
# existing dependency order.
import app.main  # noqa: F401

from app.application import check_sync
from app.check.schemas import CheckRunImportSummary
from app.github.schemas import GitHubCheckRun


def test_github_check_run_schema_preserves_associated_pr_numbers() -> None:
    run = GitHubCheckRun.model_validate(
        {
            "id": 1001,
            "name": "test",
            "head_sha": "shared-sha",
            "status": "completed",
            "conclusion": "failure",
            "details_url": "https://example.test/run",
            "started_at": None,
            "completed_at": None,
            "pull_requests": [{"number": 168}],
        }
    )

    assert [pr.number for pr in run.pull_requests] == [168]


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
    check_runs = [
        SimpleNamespace(
            pull_requests=[SimpleNamespace(number=164)],
        )
    ]
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


def test_import_check_runs_excludes_associations_to_other_prs(monkeypatch) -> None:
    db = object()
    pull_request = SimpleNamespace(
        id=177,
        number=167,
        repository=SimpleNamespace(owner="azuzm", name="event-checker"),
    )
    github_pull_request = SimpleNamespace(
        head=SimpleNamespace(sha="shared-head-sha"),
    )
    own_run = SimpleNamespace(
        id=1,
        head_sha="shared-head-sha",
        pull_requests=[SimpleNamespace(number=167)],
    )
    other_pr_run = SimpleNamespace(
        id=2,
        head_sha="shared-head-sha",
        pull_requests=[SimpleNamespace(number=168)],
    )
    unassociated_run = SimpleNamespace(
        id=3,
        head_sha="shared-head-sha",
        pull_requests=[],
    )
    github = Mock()
    github.get_pull_request.return_value = github_pull_request
    github.list_check_runs.return_value = [
        own_run,
        other_pr_run,
        unassociated_run,
    ]
    check_service = Mock()
    check_service.import_check_runs.return_value = CheckRunImportSummary(
        imported=2,
        skipped=0,
        total=2,
    )

    monkeypatch.setattr(check_sync, "GitHubService", lambda: github)
    monkeypatch.setattr(
        check_sync,
        "CheckRunService",
        lambda: check_service,
    )

    check_sync.CheckSyncService().import_check_runs(
        db=db,
        pull_request=pull_request,
    )

    check_service.import_check_runs.assert_called_once_with(
        db=db,
        pull_request_id=177,
        check_runs=[own_run, unassociated_run],
    )
