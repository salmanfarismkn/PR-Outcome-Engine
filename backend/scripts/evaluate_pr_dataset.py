from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401
from sqlalchemy import func, select

from app.check.models import CheckRun
from app.dataset.service import TrainingDatasetService
from app.db.session import SessionLocal
from app.feature.models import PRFeatureSnapshot
from app.ml.model import FEATURE_COLUMNS
from app.ml.service import PRRiskModelService
from app.outcome.models import PullRequestOutcome
from app.pull_request.models import PullRequest
from app.repository.models import Repository


SYNTHETIC_INDICATORS = re.compile(
    r"\b(dataset|synthetic|automated|generated|test|fixture|example)\b",
    re.IGNORECASE,
)


def evaluate_dataset(dataset: list[dict]) -> dict:
    try:
        result = PRRiskModelService().train(dataset, save_model=False)
    except ValueError as exc:
        return {
            "evaluation_status": "not_evaluable",
            "evaluation_reason": str(exc),
        }

    return {
        "evaluation_status": "evaluated",
        "evaluation": {
            "method": result["metrics"]["split_strategy"],
            "training_rows": result["training_rows"],
            "testing_rows": result["testing_rows"],
            "metrics": result["metrics"],
        },
    }


def _check_counts(checks: list[CheckRun]) -> dict[str, int]:
    return {
        "total": len(checks),
        "successful": sum(
            check.status == "completed" and check.conclusion == "success"
            for check in checks
        ),
        "failed": sum(
            check.status == "completed" and check.conclusion == "failure"
            for check in checks
        ),
        "cancelled": sum(
            check.status == "completed" and check.conclusion == "cancelled"
            for check in checks
        ),
        "timed_out": sum(
            check.status == "completed" and check.conclusion == "timed_out"
            for check in checks
        ),
        "pending": sum(check.status in {"queued", "waiting", "requested"} for check in checks),
        "in_progress": sum(check.status == "in_progress" for check in checks),
        "other_completed": sum(
            check.status == "completed"
            and check.conclusion
            not in {"success", "failure", "cancelled", "timed_out"}
            for check in checks
        ),
        "missing_sha": sum(not check.head_sha for check in checks),
    }


def main() -> None:
    with SessionLocal() as db:
        total_pull_requests = db.scalar(
            select(func.count(PullRequest.id))
        ) or 0
        check_run_count = db.scalar(
            select(func.count(CheckRun.id))
        ) or 0
        prs_with_checks = db.scalar(
            select(func.count(func.distinct(CheckRun.pull_request_id)))
        ) or 0
        outcome_counts = dict(
            db.execute(
                select(
                    PullRequestOutcome.outcome,
                    func.count(PullRequestOutcome.id),
                ).group_by(PullRequestOutcome.outcome)
            ).all()
        )
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
            .order_by(PullRequestOutcome.outcome, PullRequest.id)
        ).all()
        pull_request_ids = [pull_request.id for _, pull_request, _ in outcomes]
        checks_by_pr: dict[int, list[CheckRun]] = defaultdict(list)
        snapshots_by_pr: dict[int, list[PRFeatureSnapshot]] = defaultdict(list)
        if pull_request_ids:
            for check in db.scalars(
                select(CheckRun).where(
                    CheckRun.pull_request_id.in_(pull_request_ids)
                )
            ):
                checks_by_pr[check.pull_request_id].append(check)
            for snapshot in db.scalars(
                select(PRFeatureSnapshot).where(
                    PRFeatureSnapshot.pull_request_id.in_(pull_request_ids)
                )
            ):
                snapshots_by_pr[snapshot.pull_request_id].append(snapshot)
        dataset = TrainingDatasetService().build_dataset(db)

    dataset_ids = {row["pull_request_id"] for row in dataset}
    outcome_audits = []
    for outcome, pull_request, repository in outcomes:
        checks = checks_by_pr[pull_request.id]
        current_checks = [
            check
            for check in checks
            if pull_request.head_sha and check.head_sha == pull_request.head_sha
        ]
        snapshots = snapshots_by_pr[pull_request.id]
        eligible_snapshots = [
            snapshot
            for snapshot in snapshots
            if outcome.merged_at is not None
            and TrainingDatasetService._as_utc(snapshot.created_at)
            <= TrainingDatasetService._as_utc(outcome.merged_at)
            and snapshot.commit_count > 0
            and snapshot.changed_files > 0
        ]
        eligible_snapshots.sort(key=lambda item: item.created_at, reverse=True)

        if outcome.merged_at is None:
            exclusion_reason = "missing_merge_timestamp"
        elif not eligible_snapshots:
            exclusion_reason = "no_complete_snapshot_at_or_before_merge"
        elif pull_request.id not in dataset_ids:
            exclusion_reason = "eligible_snapshot_but_no_dataset_row"
        else:
            exclusion_reason = None

        sha_counts = Counter(check.head_sha or "<missing>" for check in checks)
        outcome_audits.append(
            {
                "outcome": outcome.outcome,
                "internal_pr_id": pull_request.id,
                "github_pr_number": pull_request.number,
                "repository": f"{repository.owner}/{repository.name}",
                "title": pull_request.title,
                "author": pull_request.author,
                "synthetic_indicator_in_title_or_repo": bool(
                    SYNTHETIC_INDICATORS.search(
                        f"{pull_request.title} {repository.owner}/{repository.name}"
                    )
                ),
                "reason": outcome.reason,
                "merged_at": outcome.merged_at,
                "current_head_sha": pull_request.head_sha,
                "check_run_count": len(checks),
                "check_sha_counts": dict(sha_counts),
                "checks_all_associated_shas": _check_counts(checks),
                "checks_for_current_head": _check_counts(current_checks),
                "checks_with_other_sha": len(checks) - len(current_checks),
                "snapshot_count": len(snapshots),
                "eligible_snapshot_count": len(eligible_snapshots),
                "snapshots": [
                    {
                        "id": snapshot.id,
                        "created_at": snapshot.created_at,
                        "complete": (
                            snapshot.commit_count > 0
                            and snapshot.changed_files > 0
                        ),
                        "at_or_before_merge": (
                            outcome.merged_at is not None
                            and TrainingDatasetService._as_utc(
                                snapshot.created_at
                            )
                            <= TrainingDatasetService._as_utc(
                                outcome.merged_at
                            )
                        ),
                        "commit_count": snapshot.commit_count,
                        "changed_files": snapshot.changed_files,
                    }
                    for snapshot in sorted(
                        snapshots,
                        key=lambda item: item.created_at,
                    )
                ],
                "selected_snapshot": (
                    {
                        "id": eligible_snapshots[0].id,
                        "created_at": eligible_snapshots[0].created_at,
                        "commit_count": eligible_snapshots[0].commit_count,
                        "changed_files": eligible_snapshots[0].changed_files,
                    }
                    if eligible_snapshots
                    else None
                ),
                "dataset_included": pull_request.id in dataset_ids,
                "exclusion_reason": exclusion_reason,
            }
        )

    healthy_audits = [
        item for item in outcome_audits if item["outcome"] == "healthy"
    ]
    problematic_audits = [
        item for item in outcome_audits if item["outcome"] == "problematic"
    ]

    problematic_groups: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
    for item in problematic_audits:
        problematic_groups[(item["reason"] or "<no reason>", item["exclusion_reason"])].append(item)

    problematic_summary = []
    for (reason, exclusion_reason), items in sorted(
        problematic_groups.items(),
        key=lambda pair: (-len(pair[1]), pair[0][0], str(pair[0][1])),
    ):
        problematic_summary.append(
            {
                "reason": reason,
                "dataset_status": (
                    exclusion_reason or "included"
                ),
                "count": len(items),
                "synthetic_indicator_count": sum(
                    item["synthetic_indicator_in_title_or_repo"]
                    for item in items
                ),
                "sample": items[:5],
            }
        )

    labels = Counter(row["label"] for row in dataset)
    unique_pr_ids = {row["pull_request_id"] for row in dataset}
    features = {}
    for feature in FEATURE_COLUMNS:
        values = [row.get(feature) for row in dataset]
        present = [value for value in values if value is not None]
        distinct = len(set(present))
        features[feature] = {
            "present": len(present),
            "missing": len(values) - len(present),
            "distinct": distinct,
            "constant": bool(present) and distinct == 1,
        }

    report = {
        "pull_requests_total": total_pull_requests,
        "check_runs_total": check_run_count,
        "pull_requests_with_checks": prs_with_checks,
        "outcome_counts": outcome_counts,
        "training_rows": len(dataset),
        "distinct_pull_request_ids": len(unique_pr_ids),
        "duplicate_pr_rows": len(dataset) - len(unique_pr_ids),
        "training_label_counts": dict(labels),
        "features": features,
        "healthy_outcomes": healthy_audits,
        "problematic_outcome_count": len(problematic_audits),
        "problematic_summary_by_reason_and_eligibility": problematic_summary,
    }

    report.update(evaluate_dataset(dataset))

    print(json.dumps(report, indent=2, default=str))
    if report["evaluation_status"] == "not_evaluable":
        print(
            "Model evaluation not available: "
            f"{report['evaluation_reason']}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
