from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.application.review_sync import ReviewSyncService
from app.db.session import get_db
from app.pull_request.models import PullRequest
from app.review.schemas import ReviewImportSummary
from app.feature.service import PRFeatureService


router = APIRouter(
    prefix="/reviews",
    tags=["Reviews"],
)

review_sync_service = ReviewSyncService()


@router.post(
    "/import/{pull_request_id}",
    response_model=ReviewImportSummary,
    status_code=HTTPStatus.OK,
)
def import_reviews(
    pull_request_id: int,
    db: Session = Depends(get_db),
) -> ReviewImportSummary:

    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Pull request not found.",
        )

    summary = review_sync_service.import_reviews(
        db=db,
        pull_request=pull_request,
    )
    if not pull_request.merged:
        PRFeatureService().create_snapshot(
            db=db,
            pull_request=pull_request,
        )
    return summary