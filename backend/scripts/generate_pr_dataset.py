import argparse
import time
from datetime import datetime, timezone
import httpx
import subprocess
import sys
import tempfile
from uuid import uuid4
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.github.service import GitHubService  # noqa: E402


def run_git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(
            f"git {' '.join(args)} failed with exit code "
            f"{result.returncode}: {details}"
        )
    return result.stdout.strip()


def validate_repository(repo_path: Path, owner: str, repository: str) -> None:
    if not repo_path.is_dir():
        raise SystemExit(f"Repository path does not exist or is not a directory: {repo_path}")

    repo_root = Path(run_git(repo_path, "rev-parse", "--show-toplevel")).resolve()
    if repo_root != repo_path:
        raise SystemExit(
            f"--repo-path must point to the repository root ({repo_root}), "
            f"not {repo_path}."
        )

    origin = run_git(repo_path, "remote", "get-url", "origin")
    remote_parts = origin.removesuffix(".git").replace(":", "/").rstrip("/").split("/")

    if len(remote_parts) < 2 or [
        part.casefold() for part in remote_parts[-2:]
    ] != [owner.casefold(), repository.casefold()]:
        raise SystemExit(
            f"Repository path {repo_path} has origin {origin!r}, "
            f"but the requested GitHub repository is {owner}/{repository}. "
            "Set --repo-path to a local clone of the requested repository."
        )


def report_github_error(action: str, error: Exception) -> SystemExit:
    if isinstance(error, httpx.HTTPStatusError):
        return SystemExit(
            f"{action} failed: GitHub returned HTTP "
            f"{error.response.status_code} ({error.response.reason_phrase})."
        )
    return SystemExit(f"{action} failed: {error}")


def wait_for_ci_failure(
    *,
    github: GitHubService,
    owner: str,
    repo: str,
    pr_number: int,
    pull_request_id: int,
    timeout_seconds: int = 180,
    poll_interval_seconds: int = 3,
) -> dict:
    deadline = time.monotonic() + timeout_seconds

    status_url = (
        f"{BACKEND_URL}/dataset/pr/github/"
        f"{owner}/{repo}/{pr_number}/status"
    )
    import_url = (
        f"{BACKEND_URL}/check-runs/import/{pull_request_id}"
    )

    print(
        f"Waiting for CI failure evidence on PR #{pr_number}..."
    )

    try:
        pull_request = github.get_pull_request(
            owner,
            repo,
            pr_number,
        )
    except (
        httpx.HTTPStatusError,
        httpx.RequestError,
    ) as error:
        raise report_github_error(
            f"Could not read checks for PR #{pr_number}",
            error,
        ) from error

    with httpx.Client(timeout=10.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(status_url)
            except httpx.RequestError:
                time.sleep(poll_interval_seconds)
                continue

            if response.status_code == 404:
                time.sleep(poll_interval_seconds)
                continue

            response.raise_for_status()
            status = response.json()

            if status["failed_checks"] > 0:
                print(
                    f"CI failure confirmed: "
                    f"failed_checks={status['failed_checks']}"
                )
                return status

            try:
                check_runs = github.list_check_runs(
                    owner,
                    repo,
                    pull_request.head.ref,
                )
            except (
                httpx.HTTPStatusError,
                httpx.RequestError,
            ) as error:
                raise report_github_error(
                    f"Could not read checks for PR #{pr_number}",
                    error,
                ) from error

            has_failed_check = any(
                check.status == "completed"
                and check.conclusion in {
                    "failure",
                    "cancelled",
                    "timed_out",
                    "action_required",
                }
                for check in check_runs
            )
            if has_failed_check:
                print(
                    "GitHub reports a completed failed check; "
                    "syncing checks to the backend..."
                )
                try:
                    import_response = client.post(import_url)
                    import_response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    raise SystemExit(
                        "Could not sync GitHub checks to the backend: "
                        f"HTTP {error.response.status_code} "
                        f"({error.response.reason_phrase})."
                    ) from error
                except httpx.RequestError as error:
                    raise SystemExit(
                        "Could not sync GitHub checks to the backend: "
                        f"{error}"
                    ) from error

                response = client.get(status_url)
                response.raise_for_status()
                status = response.json()
                if status["failed_checks"] > 0:
                    print(
                        f"CI failure confirmed: "
                        f"failed_checks={status['failed_checks']}"
                    )
                    return status

            time.sleep(poll_interval_seconds)

    raise SystemExit(
        f"Timed out waiting for CI failure "
        f"on PR #{pr_number}."
    )

BACKEND_URL = "http://127.0.0.1:8000"


def wait_for_pr_status(
    *,
    owner: str,
    repo: str,
    pr_number: int,
    require_merged: bool = False,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 2,
) -> dict:
    deadline = time.monotonic() + timeout_seconds

    url = (
        f"{BACKEND_URL}/dataset/pr/github/"
        f"{owner}/{repo}/{pr_number}/status"
    )

    print(
        f"Waiting for PR #{pr_number} "
        f"to reach required backend state..."
    )

    with httpx.Client(timeout=10.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(url)

                if response.status_code == 404:
                    time.sleep(poll_interval_seconds)
                    continue

                response.raise_for_status()
                status = response.json()

            except httpx.RequestError:
                time.sleep(poll_interval_seconds)
                continue

            if (
                status["snapshot_created"]
                and status["outcome_created"]
                and (
                    not require_merged
                    or status["merged"]
                )
            ):
                return status

            time.sleep(poll_interval_seconds)

    raise SystemExit(
        f"Timed out waiting for PR #{pr_number} "
        "to reach the required backend state."
    )

def generate_one_pr(
    github: GitHubService,
    repo_path: Path,
    owner: str,
    repository: str,
    base_branch: str,
    scenario: str,
) -> None:
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        + "-"
        + uuid4().hex[:8]
    )

    branch = f"dataset/auto-pr-{run_id}"
    filename = f"dataset_generated_{run_id}.txt"

    print()
    print("=" * 60)
    print(f"Generating dataset PR: {run_id}")
    print("=" * 60)

    print(
        f"Fetching {base_branch} and creating an isolated worktree..."
    )

    run_git(
        repo_path,
        "fetch",
        "origin",
        base_branch,
    )

    with tempfile.TemporaryDirectory(
        prefix="pr-analyzer-dataset-"
    ) as temp_dir:

        worktree_path = Path(temp_dir) / "repository"

        run_git(
            repo_path,
            "worktree",
            "add",
            "--detach",
            str(worktree_path),
            f"origin/{base_branch}",
        )

        try:
            run_git(
                worktree_path,
                "switch",
                "-c",
                branch,
            )

            dataset_file = worktree_path / filename

            dataset_file.write_text(
                f"Automated PR dataset example {run_id}\n",
                encoding="utf-8",
            )

            run_git(
                worktree_path,
                "add",
                "--",
                filename,
            )

            if scenario == "ci_failure":
                failure_marker = worktree_path / ".dataset-ci-failure"

                failure_marker.write_text(
                    "Intentional CI failure for PR Risk Analyzer dataset generation.\n",
                    encoding="utf-8",
                )

                run_git(
                    worktree_path,
                    "add",
                    "--",
                    ".dataset-ci-failure",
                )

            run_git(
                worktree_path,
                "commit",
                "-m",
                f"dataset: automated PR example {run_id}",
            )

            print("Checking push access...")

            run_git(
                worktree_path,
                "push",
                "--dry-run",
                "origin",
                f"HEAD:refs/heads/{branch}",
            )

            print("Pushing branch...")

            run_git(
                worktree_path,
                "push",
                "--set-upstream",
                "origin",
                branch,
            )

            print("Creating GitHub PR...")

            try:
                pr = github.create_pull_request(
                    owner=owner,
                    repository=repository,
                    title=f"Dataset: automated PR example {run_id}",
                    body=(
                        "Automated PR created by the "
                        "PR Risk Analyzer dataset generator."
                    ),
                    head=branch,
                    base=base_branch,
                )

            except (
                httpx.HTTPStatusError,
                httpx.RequestError,
            ) as error:
                raise report_github_error(
                    f"PR creation failed after pushing branch {branch}",
                    error,
                ) from error

            print()
            print("PR created successfully.")
            print(f"PR number: {pr.number}")
            print(f"PR title: {pr.title}")

            status = wait_for_pr_status(
                owner=owner,
                repo=repository,
                pr_number=pr.number,
            )
            
            if scenario == "ci_failure":
                status = wait_for_ci_failure(
                    github=github,
                    owner=owner,
                    repo=repository,
                    pr_number=pr.number,
                    pull_request_id=status["pull_request_id"],
                )

                print(
                    "Problematic CI evidence confirmed."
                )
                
            print(
                "PR processing confirmed: "
                f"snapshot={status['snapshot_created']}, "
                f"outcome={status['outcome']}"
            )

            print("Merging PR...")

            try:
                merge_result = github.merge_pull_request(
                    owner=owner,
                    repository=repository,
                    pull_number=pr.number,
                )
            except (
                httpx.HTTPStatusError,
                httpx.RequestError,
            ) as error:
                raise report_github_error(
                    f"PR #{pr.number} merge failed",
                    error,
                ) from error

            if not merge_result.get("merged"):
                raise SystemExit(
                    f"GitHub did not merge PR #{pr.number}: "
                    f"{merge_result}"
                )

            print("Merge result: True")

            status = wait_for_pr_status(
                owner=owner,
                repo=repository,
                pr_number=pr.number,
                require_merged=True,
            )

            print()
            print("Dataset example confirmed.")
            print(
                f"PR #{pr.number}: "
                f"lifecycle={status['lifecycle_status']}, "
                f"outcome={status['outcome']}"
            )

        finally:
            run_git(
                repo_path,
                "worktree",
                "remove",
                "--force",
                str(worktree_path),
            )

def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of real GitHub PR dataset examples to generate.",
    )
    parser.add_argument(
        "--scenario",
        choices=["healthy", "ci_failure"],
        default="healthy",
        help="Dataset scenario to generate.",
    )
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be at least 1.")

    repo_path = Path(args.repo_path).resolve()

    validate_repository(
        repo_path,
        args.owner,
        args.repo,
    )

    github = GitHubService()

    try:
        try:
            user = github.get_authenticated_user()
            target = github.get_repository(
                args.owner,
                args.repo,
            )
        except (
            httpx.HTTPStatusError,
            httpx.RequestError,
        ) as error:
            raise report_github_error(
                "GitHub access check",
                error,
            ) from error

        if (
            target.full_name.casefold()
            != f"{args.owner}/{args.repo}".casefold()
        ):
            raise SystemExit(
                f"GitHub resolved the requested repository to "
                f"{target.full_name!r}, not "
                f"{args.owner}/{args.repo}."
            )

        if (
            target.permissions is None
            or not target.permissions.push
        ):
            raise SystemExit(
                f"The GitHub token for {user.login} does not "
                f"have push permission for "
                f"{target.full_name}. Grant repository "
                "Contents: read/write and Pull requests: "
                "read/write to the token."
            )

        base_branch = target.default_branch

        for index in range(args.count):
            print(
                f"\nDataset generation "
                f"{index + 1}/{args.count}"
            )

            generate_one_pr(
                github=github,
                repo_path=repo_path,
                owner=args.owner,
                repository=args.repo,
                base_branch=base_branch,
                scenario=args.scenario,
            )

    finally:
        github.close()


if __name__ == "__main__":
    main()