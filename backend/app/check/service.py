from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.check.models import CheckRun
from app.check.schemas import CheckRunImportSummary
from app.github.schemas import GitHubCheckRun


class CheckRunService:


    def import_check_runs(
        self,
        db: Session,
        pull_request_id: int,
        check_runs: list[GitHubCheckRun],
    ) -> CheckRunImportSummary:
        imported = 0
        skipped = 0
        updated = 0

        existing_runs = {}
        check_ids = {check.id for check in check_runs}
        if check_ids:
            existing_runs = {
                check.github_id: check
                for check in db.scalars(
                    select(CheckRun).where(
                        CheckRun.github_id.in_(check_ids)
                    )
                ).all()
            }

        for check in check_runs:
            existing = existing_runs.get(check.id)

            if existing is not None:
                if existing.pull_request_id != pull_request_id:
                    skipped += 1
                    continue

                changed = (
                    existing.name != check.name
                    or existing.head_sha != check.head_sha
                    or existing.status != check.status
                    or existing.conclusion != check.conclusion
                    or existing.details_url != check.details_url
                    or existing.started_at != check.started_at
                    or existing.completed_at != check.completed_at
                )

                if changed:
                    existing.name = check.name
                    existing.head_sha = check.head_sha
                    existing.status = check.status
                    existing.conclusion = check.conclusion
                    existing.details_url = check.details_url
                    existing.started_at = check.started_at
                    existing.completed_at = check.completed_at
                    updated += 1
                else:
                    skipped += 1

                continue

            record = CheckRun(
                github_id=check.id,
                pull_request_id=pull_request_id,
                head_sha=check.head_sha,
                name=check.name,
                status=check.status,
                conclusion=check.conclusion,
                details_url=check.details_url,
                started_at=check.started_at,
                completed_at=check.completed_at,
            )
            db.add(record)
            existing_runs[check.id] = record
            imported += 1

        db.commit()

        return CheckRunImportSummary(
            imported=imported,
            skipped=skipped,
            total=len(check_runs),
            updated=updated,
        )


    def list_check_runs(
        self,
        db: Session,
        pull_request_id: int,
    ) -> list[CheckRun]:

        return list(
            db.scalars(
                select(CheckRun)
                .where(
                    CheckRun.pull_request_id == pull_request_id
                )
                .order_by(CheckRun.id)
            )
        )