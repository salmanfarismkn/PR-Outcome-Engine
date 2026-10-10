from __future__ import annotations

from sqlalchemy.orm import Session

from app.github.service import GitHubService
from app.pull_request.models import PullRequest
from app.review.schemas import ReviewImportSummary
from app.review.service import ReviewService


class ReviewSyncService:
    def __init__(self) -> None:
        self._github = GitHubService()
        self._review_service = ReviewService()

    def import_reviews(
        self,
        db: Session,
        pull_request: PullRequest,
    ) -> ReviewImportSummary:

        owner = pull_request.repository.owner
        repository = pull_request.repository.name
        print(
            "[review-import-debug] resolving reviews: "
            f"internal_pull_request_id={pull_request.id}, "
            f"github_repository={owner}/{repository}, "
            f"github_pull_number={pull_request.number}",
            flush=True,
        )

        reviews = self._github.list_reviews(
            owner=owner,
            repository=repository,
            pull_number=pull_request.number,
        )
        print(
            "[review-import-debug] GitHub returned typed reviews: "
            f"count={len(reviews)}",
            flush=True,
        )

        summary = self._review_service.import_reviews(
            db=db,
            pull_request_id=pull_request.id,
            reviews=reviews,
        )
        print(
            "[review-import-debug] import complete: "
            f"imported={summary.imported}, "
            f"skipped={summary.skipped}, "
            f"total={summary.total}",
            flush=True,
        )
        return summary