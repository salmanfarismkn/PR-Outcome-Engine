from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dataset.service import TrainingDatasetService
from app.db.session import SessionLocal
from app.feature.models import PRFeatureSnapshot
from app.ml.service import PRRiskModelService
from app.outcome.models import PullRequestOutcome
from app.pull_request.models import PullRequest
from app.repository.models import Repository


def build_readiness_report(db: Session) -> dict:
    dataset = TrainingDatasetService().build_dataset(db)
    outcomes = db.execute(
        select(PullRequestOutcome, PullRequest, Repository)
        .join(
            PullRequest,
            PullRequest.id == PullRequestOutcome.pull_request_id,
        )
        .join(Repository, Repository.id == PullRequest.repository_id)
        .where(
            PullRequestOutcome.outcome.in_(["healthy", "problematic"])
        )
    ).all()

    pull_request_ids = [pull_request.id for _, pull_request, _ in outcomes]
    snapshots_by_pr: dict[int, list[PRFeatureSnapshot]] = defaultdict(list)
    if pull_request_ids:
        for snapshot in db.scalars(
            select(PRFeatureSnapshot).where(
                PRFeatureSnapshot.pull_request_id.in_(pull_request_ids)
            )
        ):
            snapshots_by_pr[snapshot.pull_request_id].append(snapshot)

    eligible_counts = Counter(
        (row["repository_id"], row["label"])
        for row in dataset
    )
    snapshot_counts: dict[tuple[int, str], Counter] = defaultdict(Counter)
    for outcome, pull_request, repository in outcomes:
        complete_premerge_snapshot = any(
            outcome.merged_at is not None
            and TrainingDatasetService._as_utc(snapshot.created_at)
            <= TrainingDatasetService._as_utc(outcome.merged_at)
            and snapshot.commit_count > 0
            and snapshot.changed_files > 0
            for snapshot in snapshots_by_pr[pull_request.id]
        )
        counts = snapshot_counts[
            (repository.id, outcome.outcome)
        ]
        counts["outcomes"] += 1
        if complete_premerge_snapshot:
            counts["complete_premerge_snapshots"] += 1
        else:
            counts["missing_complete_premerge_snapshots"] += 1

    repository_names = {
        repository.id: f"{repository.owner}/{repository.name}"
        for _, _, repository in outcomes
    }
    eligible_groups = [
        {
            "repository_id": repository_id,
            "repository": repository_names.get(repository_id),
            "outcome": outcome,
            "snapshot_completeness": "complete",
            "eligible_rows": count,
        }
        for (repository_id, outcome), count in sorted(
            eligible_counts.items()
        )
    ]
    snapshot_eligibility = [
        {
            "repository_id": repository_id,
            "repository": repository_names.get(repository_id),
            "outcome": outcome,
            **dict(counts),
            "eligible_training_rows": eligible_counts.get(
                (repository_id, outcome),
                0,
            ),
        }
        for (repository_id, outcome), counts in sorted(
            snapshot_counts.items()
        )
    ]
    class_repository_counts = {
        label: len(
            {
                row["repository_id"]
                for row in dataset
                if row["label"] == label
            }
        )
        for label in ("healthy", "problematic")
    }

    try:
        partitions = PRRiskModelService.get_partition_class_counts(dataset)
        evaluation_status = "split_available"
        evaluation_reason = None
        single_class_partition_warning = any(
            distribution["healthy"] == 0
            or distribution["problematic"] == 0
            for distribution in partitions.values()
        )
    except ValueError as exc:
        partitions = None
        evaluation_status = "not_evaluable"
        evaluation_reason = str(exc)
        single_class_partition_warning = None

    return {
        "training_rows": len(dataset),
        "distinct_pull_requests": len(
            {row["pull_request_id"] for row in dataset}
        ),
        "eligible_rows_by_repository_outcome_and_snapshot_completeness": (
            eligible_groups
        ),
        "outcome_snapshot_eligibility_by_repository_and_outcome": (
            snapshot_eligibility
        ),
        "training_label_counts": dict(
            Counter(row["label"] for row in dataset)
        ),
        "repository_count": len(
            {row["repository_id"] for row in dataset}
        ),
        "repositories_per_class": class_repository_counts,
        "repository_diversity_sufficient": all(
            count >= 2 for count in class_repository_counts.values()
        ),
        "evaluation_status": evaluation_status,
        "evaluation_reason": evaluation_reason,
        "evaluation_partition_class_counts": partitions,
        "single_class_partition_warning": single_class_partition_warning,
        "uncertain_outcomes_excluded": db.scalar(
            select(func.count(PullRequestOutcome.id)).where(
                PullRequestOutcome.outcome == "uncertain"
            )
        ) or 0,
        "model_training_performed": False,
        "model_artifact_written": False,
    }


def main() -> None:
    with SessionLocal() as db:
        report = build_readiness_report(db)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
