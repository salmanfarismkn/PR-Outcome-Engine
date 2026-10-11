from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main  # noqa: F401
from app.application.check_sync import CheckSyncService
from app.application.outcome_evaluation import OutcomeEvaluator
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.feature.service import PRFeatureService
from app.application.pull_request_sync import PullRequestSyncService
from app.check.schemas import CheckRunImportSummary
from app.outcome.models import PullRequestOutcome
from app.pull_request.models import PullRequest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def backfill_pull_request(
    db: Session,
    pull_request: PullRequest,
    pull_request_sync: PullRequestSyncService,
    check_sync: CheckSyncService,
    feature_service: PRFeatureService,
) -> tuple[CheckRunImportSummary, PullRequestOutcome]:
    pull_request_sync.sync_pull_request(
        db=db,
        pull_request=pull_request,
    )
    check_summary = check_sync.import_check_runs(
        db=db,
        pull_request=pull_request,
    )
    db.refresh(pull_request)
    if not pull_request.merged:
        feature_service.create_snapshot(
            db=db,
            pull_request=pull_request,
        )
    outcome = OutcomeEvaluator().evaluate(
        db=db,
        pull_request=pull_request,
    )
    return check_summary, outcome


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill current-head GitHub check runs and PR outcomes.",
    )
    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help="Resume with pull-request IDs greater than this value.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum pull requests to process in this run.",
    )
    args = parser.parse_args()
    if args.after_id < 0:
        raise SystemExit("--after-id must be nonnegative.")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1.")

    settings = get_settings()
    if not settings.github_token:
        raise SystemExit(
            "GITHUB_TOKEN is not configured; check-run backfill requires "
            "authenticated GitHub API access."
        )

    check_sync = CheckSyncService()
    pull_request_sync = PullRequestSyncService()
    feature_service = PRFeatureService()
    processed = failed = imported = updated = skipped = 0
    uncertain = 0
    last_pull_request_id = args.after_id

    try:
        with SessionLocal() as db:
            query = (
                select(PullRequest.id)
                .where(PullRequest.id > args.after_id)
                .order_by(PullRequest.id)
            )
            if args.limit is not None:
                query = query.limit(args.limit)
            pull_request_ids = db.scalars(query).all()
            logger.info(
                "Found %d pull requests to process (after_id=%d, limit=%s)",
                len(pull_request_ids),
                args.after_id,
                args.limit,
            )

            for pull_request_id in pull_request_ids:
                last_pull_request_id = pull_request_id
                try:
                    pull_request = db.get(PullRequest, pull_request_id)
                    if pull_request is None:
                        raise LookupError(
                            f"Pull request {pull_request_id} disappeared."
                        )

                    result, outcome = backfill_pull_request(
                        db=db,
                        pull_request=pull_request,
                        pull_request_sync=pull_request_sync,
                        check_sync=check_sync,
                        feature_service=feature_service,
                    )

                    processed += 1
                    imported += result.imported
                    updated += result.updated
                    skipped += result.skipped
                    uncertain += outcome.outcome == "uncertain"
                    logger.info(
                        "Processed PR id=%d number=%d: checks imported=%d "
                        "updated=%d skipped=%d; outcome=%s",
                        pull_request.id,
                        pull_request.number,
                        result.imported,
                        result.updated,
                        result.skipped,
                        outcome.outcome,
                    )
                except Exception:
                    db.rollback()
                    failed += 1
                    logger.exception(
                        "Failed to backfill PR id=%d",
                        pull_request_id,
                    )

    finally:
        check_sync.close()

    summary = {
        "processed": processed,
        "failed": failed,
        "checks_imported": imported,
        "checks_updated": updated,
        "checks_skipped": skipped,
        "uncertain_outcomes": uncertain,
        "last_pull_request_id": last_pull_request_id,
        "resume_with_after_id": last_pull_request_id,
    }
    logger.info("Backfill summary: %s", summary)
    if failed:
        raise SystemExit(
            f"Backfill incomplete: {failed} pull requests failed. "
            f"Resume with --after-id {last_pull_request_id} after resolving "
            "the failures."
        )


if __name__ == "__main__":
    main()
