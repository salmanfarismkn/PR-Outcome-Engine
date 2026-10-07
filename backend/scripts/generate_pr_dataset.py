import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-path", required=True)

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    validate_repository(repo_path, args.owner, args.repo)

    github = GitHubService()
    try:
        try:
            user = github.get_authenticated_user()
            target = github.get_repository(args.owner, args.repo)
        except (httpx.HTTPStatusError, httpx.RequestError) as error:
            raise report_github_error("GitHub access check", error) from error

        if target.full_name.casefold() != f"{args.owner}/{args.repo}".casefold():
            raise SystemExit(
                f"GitHub resolved the requested repository to {target.full_name!r}, "
                f"not {args.owner}/{args.repo}."
            )
        if target.permissions is None or not target.permissions.push:
            raise SystemExit(
                f"The GitHub token for {user.login} does not have push permission "
                f"for {target.full_name}. Grant repository Contents: read/write "
                "and Pull requests: read/write to the token."
            )

        base_branch = target.default_branch
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "-"
            + uuid4().hex[:8]
        )
        branch = f"dataset/auto-pr-{run_id}"
        filename = f"dataset_generated_{run_id}.txt"

        print(f"Fetching {base_branch} and creating an isolated worktree...")
        run_git(repo_path, "fetch", "origin", base_branch)

        with tempfile.TemporaryDirectory(prefix="pr-analyzer-dataset-") as temp_dir:
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
                run_git(worktree_path, "switch", "-c", branch)
                (worktree_path / filename).write_text(
                    f"Automated PR dataset example {run_id}\n",
                    encoding="utf-8",
                )
                run_git(worktree_path, "add", "--", filename)
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
                        owner=args.owner,
                        repository=args.repo,
                        title=f"Dataset: automated PR example {run_id}",
                        body=(
                            "Automated PR created by the "
                            "PR Risk Analyzer dataset generator."
                        ),
                        head=branch,
                        base=base_branch,
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as error:
                    raise report_github_error(
                        f"PR creation failed after pushing branch {branch}",
                        error,
                    ) from error

                print()
                print("PR created successfully.")
                print(f"PR number: {pr.number}")
                print(f"PR title: {pr.title}")
            finally:
                run_git(repo_path, "worktree", "remove", "--force", str(worktree_path))
    finally:
        github.close()


if __name__ == "__main__":
    main()