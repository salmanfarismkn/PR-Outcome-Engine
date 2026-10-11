from sqlalchemy.orm import Session

from app.feature.models import PRFeatureSnapshot
from app.outcome.models import PullRequestOutcome
from datetime import datetime, timezone

class TrainingDatasetService:

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def build_dataset(
        self,
        db: Session,
    ) -> list[dict]:
        outcomes = (
            db.query(PullRequestOutcome)
            .filter(
                PullRequestOutcome.outcome.in_(
                    ["healthy", "problematic"]
                )
            )
            .all()
        )

        dataset = []

        for outcome in outcomes:

            cutoff = outcome.merged_at or outcome.observed_at

            if cutoff is None:
                continue

            snapshots = (
                db.query(PRFeatureSnapshot)
                .filter(
                    PRFeatureSnapshot.pull_request_id
                    == outcome.pull_request_id
                )
                .order_by(
                    PRFeatureSnapshot.created_at.desc()
                )
                .all()
            )

            snapshot = next(
                (
                    item
                    for item in snapshots
                    if self._as_utc(item.created_at)
                    <= self._as_utc(cutoff)
                    and item.commit_count > 0
                    and item.changed_files > 0
                ),
                None,
            )

            if snapshot is None:
                continue

            dataset.append(
                {
                    "pull_request_id": snapshot.pull_request_id,
                    "additions": snapshot.additions,
                    "deletions": snapshot.deletions,
                    "changed_files": snapshot.changed_files,
                    "commit_count": snapshot.commit_count,
                    "unique_authors": snapshot.unique_authors,
                    "review_count": snapshot.review_count,
                    "unique_reviewers": snapshot.unique_reviewers,
                    "approvals": snapshot.approvals,
                    "change_requests": snapshot.change_requests,
                    "is_draft": snapshot.is_draft,
                    "age_hours": snapshot.age_hours,
                    "label": outcome.outcome,
                }
            )

        return dataset