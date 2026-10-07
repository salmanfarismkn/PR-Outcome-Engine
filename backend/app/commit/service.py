from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commit.models import Commit
from app.commit.schemas import CommitImportSummary
from app.github.schemas import GitHubCommit


class CommitService:
    """Persistence layer for Commit entities."""

    def import_commits(
        self,
        db: Session,
        pull_request_id: int | None,
        commits: list[GitHubCommit],
    ) -> CommitImportSummary:

        imported = 0
        skipped = 0

        print("[webhook-debug] commit import: existing SHA query started", flush=True)
        existing_shas = set(
            db.scalars(
                select(Commit.sha)
            ).all()
        )
        print(
            "[webhook-debug] commit import: existing SHA query returned; "
            f"count={len(existing_shas)}",
            flush=True,
        )

        for commit in commits:

            if commit.sha in existing_shas:
                print(
                    "[webhook-debug] commit import: existing commit query started; "
                    f"sha={commit.sha}",
                    flush=True,
                )
                existing_commit = db.scalar(
                    select(Commit).where(
                        Commit.sha == commit.sha
                    )
                )
                print(
                    "[webhook-debug] commit import: existing commit query returned; "
                    f"found={existing_commit is not None}",
                    flush=True,
                )

                if (
                    existing_commit is not None
                    and existing_commit.pull_request_id is None
                    and pull_request_id is not None
                ):
                    existing_commit.pull_request_id = pull_request_id

                skipped += 1
                continue

            db.add(
                Commit(
                    pull_request_id=pull_request_id,
                    sha=commit.sha,
                    message=commit.commit.message,
                    author_name=commit.commit.author.name,
                    author_email=commit.commit.author.email,
                    committed_at=commit.commit.author.date,
                )
            )

            imported += 1

        print("[webhook-debug] commit import: commit started", flush=True)
        db.commit()
        print("[webhook-debug] commit import: commit returned", flush=True)

        return CommitImportSummary(
            imported=imported,
            skipped=skipped,
            total=len(commits),
        )

    def list_commits(
        self,
        db: Session,
        pull_request_id: int,
    ) -> list[Commit]:

        return list(
            db.scalars(
                select(Commit)
                .where(
                    Commit.pull_request_id == pull_request_id
                )
                .order_by(
                    Commit.committed_at
                )
            )
        )

    def get_commit_by_sha(
        self,
        db: Session,
        sha: str,
    ) -> Commit | None:

        return db.scalar(
            select(Commit).where(
                Commit.sha == sha
            )
        )