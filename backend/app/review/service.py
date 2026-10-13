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
        updated = 0
        skipped = 0

        if not reviews:
            return ReviewImportSummary(
                imported=0,
                updated=0,
                skipped=0,
                total=0,
            )

        review_ids = {review.id for review in reviews}
        existing_reviews = {
            review.github_id: review
            for review in db.scalars(
                select(Review).where(
                    Review.github_id.in_(review_ids)
                )
            ).all()
        }

        for review in reviews:
            existing = existing_reviews.get(review.id)
            if (
                existing is not None
                and existing.pull_request_id != pull_request_id
            ):
                raise ValueError(
                    f"GitHub review {review.id} is already associated "
                    f"with internal pull request "
                    f"{existing.pull_request_id}, not {pull_request_id}."
                )

        for review in reviews:
            existing = existing_reviews.get(review.id)
            reviewer_login = review.user.login if review.user else None
            if reviewer_login is None:
                print(
                    "[review-import-debug] reviewer missing; "
                    f"preserving known reviewer or using 'unknown' for "
                    f"github_review_id={review.id}",
                    flush=True,
                )

            if existing is None:
                existing = Review(
                    github_id=review.id,
                    pull_request_id=pull_request_id,
                    reviewer_login=reviewer_login or "unknown",
                    state=review.state,
                    body=review.body,
                    submitted_at=review.submitted_at,
                )
                db.add(existing)
                existing_reviews[review.id] = existing
                imported += 1
                continue

            changes = {
                "state": review.state,
                "body": review.body,
                "submitted_at": review.submitted_at,
            }
            if reviewer_login is not None:
                changes["reviewer_login"] = reviewer_login

            changed = False
            for field, value in changes.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True

            if changed:
                updated += 1
            else:
                skipped += 1

        if imported or updated:
            db.commit()

        return ReviewImportSummary(
            imported=imported,
            updated=updated,
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