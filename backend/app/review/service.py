from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.github.schemas import GitHubReview
from app.review.models import Review
from app.review.schemas import ReviewImportSummary


class ReviewService:
    def import_reviews(
        self,
        db: Session,
        pull_request_id: int,
        reviews: list[GitHubReview],
    ) -> ReviewImportSummary:

        imported = 0
        skipped = 0

        existing_ids = set(
            db.scalars(
                select(Review.github_id)
                .where(
                    Review.pull_request_id == pull_request_id
                )
            ).all()
        )

        for review in reviews:

            if review.id in existing_ids:
                skipped += 1
                print(
                    "[review-import-debug] skipped review: "
                    f"github_review_id={review.id}, "
                    "reason=duplicate GitHub review ID already stored "
                    f"for internal_pull_request_id={pull_request_id}",
                    flush=True,
                )
                continue

            reviewer_login = (
                review.user.login
                if review.user
                else "unknown"
            )
            if review.user is None:
                print(
                    "[review-import-debug] reviewer missing; "
                    f"using 'unknown' for github_review_id={review.id}",
                    flush=True,
                )

            db.add(
                Review(
                    github_id=review.id,
                    pull_request_id=pull_request_id,
                    reviewer_login=reviewer_login,
                    state=review.state,
                    body=review.body,
                    submitted_at=review.submitted_at,
                )
            )

            imported += 1
            print(
                "[review-import-debug] imported review: "
                f"github_review_id={review.id}, "
                f"state={review.state!r}, "
                f"reviewer={reviewer_login!r}",
                flush=True,
            )

        db.commit()

        return ReviewImportSummary(
            imported=imported,
            skipped=skipped,
            total=len(reviews),
        )

    def list_reviews(
        self,
        db: Session,
        pull_request_id: int,
    ) -> list[Review]:

        return list(
            db.scalars(
                select(Review)
                .where(
                    Review.pull_request_id == pull_request_id
                )
                .order_by(Review.submitted_at)
            )
        )