from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dataset.service import TrainingDatasetService
from fastapi import HTTPException
from sqlalchemy import select

from app.pull_request.models import PullRequest
from app.feature.models import PRFeatureSnapshot
from app.outcome.models import PullRequestOutcome
from app.repository.models import Repository

router = APIRouter(
    prefix="/dataset",
    tags=["dataset"],
)


@router.get("/training")
def get_training_dataset(
    db: Session = Depends(get_db),
):
    service = TrainingDatasetService()

    return {
        "count": len(
            service.build_dataset(db)
        ),
        "data": service.build_dataset(db),
    }



@router.get("/pr/github/{owner}/{repo}/{pr_number}/status")
def get_pr_dataset_status(
    owner: str,
    repo: str,
    pr_number: int,
    db: Session = Depends(get_db),
):
    pull_request = db.scalar(
        select(PullRequest)
        .join(PullRequest.repository)
        .where(
            PullRequest.number == pr_number,
            Repository.owner == owner,
            Repository.name == repo,
        )
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull request not found.",
        )

    snapshot = db.scalar(
        select(PRFeatureSnapshot)
        .where(
            PRFeatureSnapshot.pull_request_id == pull_request.id
        )
        .order_by(
            PRFeatureSnapshot.created_at.desc()
        )
    )

    outcome = db.scalar(
        select(PullRequestOutcome).where(
            PullRequestOutcome.pull_request_id
            == pull_request.id
        )
    )

    return {
        "pull_request_id": pull_request.id,
        "github_id": pull_request.github_id,
        "number": pull_request.number,
        "merged": pull_request.merged,
        "state": pull_request.state,
        "snapshot_created": snapshot is not None,
        "outcome_created": outcome is not None,
        "lifecycle_status": (
            outcome.lifecycle_status
            if outcome is not None
            else None
        ),
        "outcome": (
            outcome.outcome
            if outcome is not None
            else None
        ),
    }