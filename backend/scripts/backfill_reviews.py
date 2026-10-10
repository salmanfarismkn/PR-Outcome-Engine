from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.session import SessionLocal
from app.application.review_sync import ReviewSyncService
from app.feature.service import PRFeatureService
from app.pull_request.models import PullRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    review_sync = ReviewSyncService()
    feature_service = PRFeatureService()

    processed = 0
    failed = 0
    imported_reviews = 0
    skipped_reviews = 0
    total_reviews = 0
    snapshots_refreshed = 0

    with SessionLocal() as db:
        pull_requests = db.scalars(
            select(PullRequest).order_by(PullRequest.id)
        ).all()

        logger.info("Found %d pull requests", len(pull_requests))

        for pull_request in pull_requests:
            try:
                result = review_sync.import_reviews(
                    db=db,
                    pull_request=pull_request,
                )

                imported_reviews += result.imported
                skipped_reviews += result.skipped
                total_reviews += result.total

                feature_service.create_snapshot(
                    db=db,
                    pull_request=pull_request,
                )

                processed += 1
                snapshots_refreshed += 1

                logger.info(
                    "Processed PR id=%s number=%s: "
                    "imported=%d skipped=%d total=%d",
                    pull_request.id,
                    pull_request.number,
                    result.imported,
                    result.skipped,
                    result.total,
                )

            except Exception:
                db.rollback()
                failed += 1
                logger.exception(
                    "Failed PR id=%s number=%s",
                    pull_request.id,
                    pull_request.number,
                )

    logger.info(
        "Backfill complete: processed=%d snapshots_refreshed=%d "
        "failed=%d imported_reviews=%d skipped_reviews=%d "
        "reviews_seen=%d",
        processed,
        snapshots_refreshed,
        failed,
        imported_reviews,
        skipped_reviews,
        total_reviews,
    )


if __name__ == "__main__":
    main()
