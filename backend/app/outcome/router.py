from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.outcome.service import OutcomeEvaluator
from app.pull_request.models import PullRequest
from app.api.dependencies import require_admin_access


router = APIRouter(
    prefix="/outcomes",
    tags=["outcomes"],
)


@router.post(
    "/pull-request/{pull_request_id}",
    dependencies=[Depends(require_admin_access)],
)
def evaluate_pull_request(
    pull_request_id: int,
    db: Session = Depends(get_db),
):
    pull_request = (
        db.query(PullRequest)
        .filter(PullRequest.id == pull_request_id)
        .first()
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull request not found",
        )

    evaluator = OutcomeEvaluator()

    outcome = evaluator.evaluate(
        db=db,
        pull_request=pull_request,
    )

    return {
        "id": outcome.id,
        "pull_request_id": outcome.pull_request_id,
        "lifecycle_status": outcome.lifecycle_status,
        "outcome": outcome.outcome,
        "reason": outcome.reason,
        "merged_at": outcome.merged_at,
        "observed_at": outcome.observed_at,
    }