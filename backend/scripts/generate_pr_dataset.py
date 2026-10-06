import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path

from app.github.client import GitHubClient


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def create_pr(
    repo_path: Path,
    github_client: GitHubClient,
    owner: str,
    repo: str,
    index: int,
):
    branch = f"dataset/pr-{index}"

    run(
        ["git", "checkout", "-b", branch],
        cwd=repo_path,
    )

    file_path = repo_path / "dataset_generated.txt"

    existing = ""

    if file_path.exists():
        existing = file_path.read_text()

    file_path.write_text(
        existing
        + f"\nGenerated dataset PR {index}\n"
    )

    run(
        ["git", "add", "dataset_generated.txt"],
        cwd=repo_path,
    )

    run(
        [
            "git",
            "commit",
            "-m",
            f"dataset: generated PR {index}",
        ],
        cwd=repo_path,
    )

    run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo_path,
    )

    # GitHub API call.
    pr = github_client.create_pull_request(
        owner=owner,
        repo=repo,
        title=f"Dataset PR {index}",
        body=(
            "Automatically generated PR for "
            "PR Risk Analyzer training data."
        ),
        head=branch,
        base="main",
    )

    return pr


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--count",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--owner",
        required=True,
    )

    parser.add_argument(
        "--repo",
        required=True,
    )

    parser.add_argument(
        "--repo-path",
        required=True,
    )

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()

    github_client = GitHubClient()

    for index in range(
        1,
        args.count + 1,
    ):
        print(
            f"\n=== Generating PR {index}/{args.count} ==="
        )

        try:
            pr = create_pr(
                repo_path=repo_path,
                github_client=github_client,
                owner=args.owner,
                repo=args.repo,
                index=index,
            )

            print(
                f"Created PR #{pr.number}"
            )

            print(
                "Waiting for webhook processing..."
            )

            time.sleep(5)

            # Return to main before creating
            # the next branch.
            run(
                ["git", "checkout", "main"],
                cwd=repo_path,
            )

            print(
                f"PR #{pr.number} created successfully."
            )

        except Exception as exc:
            print(
                f"Failed to generate PR {index}: {exc}"
            )

            try:
                run(
                    ["git", "checkout", "main"],
                    cwd=repo_path,
                )
            except Exception:
                pass


if __name__ == "__main__":
    main()