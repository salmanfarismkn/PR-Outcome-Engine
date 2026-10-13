from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import generate_pr_dataset


def test_checks_for_pull_request_uses_current_sha_and_association() -> None:
    own_run = SimpleNamespace(
        head_sha="current",
        pull_requests=[SimpleNamespace(number=167)],
    )
    other_pr_run = SimpleNamespace(
        head_sha="current",
        pull_requests=[SimpleNamespace(number=168)],
    )
    old_sha_run = SimpleNamespace(
        head_sha="old",
        pull_requests=[SimpleNamespace(number=167)],
    )
    unassociated_run = SimpleNamespace(
        head_sha="current",
        pull_requests=[],
    )

    assert generate_pr_dataset.checks_for_pull_request(
        [own_run, other_pr_run, old_sha_run, unassociated_run],
        pr_number=167,
        head_sha="current",
    ) == [own_run, unassociated_run]


def test_healthy_scenario_waits_for_pending_and_rejects_failures() -> None:
    pending = SimpleNamespace(
        name="tests",
        status="in_progress",
        conclusion=None,
    )
    successful = SimpleNamespace(
        name="tests",
        status="completed",
        conclusion="success",
    )
    failing = SimpleNamespace(
        name="tests",
        status="completed",
        conclusion="failure",
    )

    assert generate_pr_dataset.healthy_scenario_check_state(
        [pending]
    ) == ("pending", None)
    assert generate_pr_dataset.healthy_scenario_check_state(
        [successful]
    ) == ("success", None)
    assert generate_pr_dataset.healthy_scenario_check_state(
        [failing]
    ) == ("failed", "tests=failure")


def test_healthy_scenario_removes_inherited_failure_marker(
    tmp_path: Path,
) -> None:
    generate_pr_dataset.run_git(tmp_path, "init", "-q")
    generate_pr_dataset.run_git(
        tmp_path,
        "config",
        "user.name",
        "Dataset Generator Test",
    )
    generate_pr_dataset.run_git(
        tmp_path,
        "config",
        "user.email",
        "dataset-test@example.invalid",
    )
    marker = tmp_path / ".dataset-ci-failure"
    marker.write_text("inherited marker\n", encoding="utf-8")
    generate_pr_dataset.run_git(
        tmp_path,
        "add",
        "--",
        ".dataset-ci-failure",
    )
    generate_pr_dataset.run_git(
        tmp_path,
        "commit",
        "-m",
        "add inherited CI failure marker",
    )

    generate_pr_dataset.prepare_scenario_marker(tmp_path, "healthy")

    assert not marker.exists()
    assert generate_pr_dataset.run_git(
        tmp_path,
        "diff",
        "--cached",
        "--name-status",
    ) == "D\t.dataset-ci-failure"


def test_generated_scenario_must_match_final_outcome() -> None:
    generate_pr_dataset.validate_scenario_outcome("healthy", "healthy")
    generate_pr_dataset.validate_scenario_outcome(
        "ci_failure",
        "problematic",
    )

    with pytest.raises(SystemExit, match="expected 'healthy'"):
        generate_pr_dataset.validate_scenario_outcome(
            "healthy",
            "problematic",
        )
