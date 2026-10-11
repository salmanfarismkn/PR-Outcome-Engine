
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dataset.service import TrainingDatasetService
from app.ml.service import PRRiskModelService

from sqlalchemy import select

from app.feature.models import PRFeatureSnapshot
from app.pull_request.models import PullRequest
from app.ml.schemas import PRRiskPredictionResponse

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


@router.post("/train")
def train_pr_risk_model(
    db: Session = Depends(get_db),
):
    dataset = TrainingDatasetService().build_dataset(db)

    try:
        result = PRRiskModelService().train(dataset)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "status": "trained",
        "dataset_rows": len(dataset),
        "training_rows": result["training_rows"],
        "testing_rows": result["testing_rows"],
        "model_path": result["model_path"],
        "metrics": result["metrics"],
        "feature_columns": result["feature_columns"],
    }

@router.post(
    "/predict/{pull_request_id}",
    response_model=PRRiskPredictionResponse,
)
def predict_pull_request_risk(
    pull_request_id: int,
    db: Session = Depends(get_db),
):
    pull_request, snapshot = get_pre_merge_snapshot(
        db=db,
        pull_request_id=pull_request_id,
    )

    features = {
        "additions": snapshot.additions,
        "deletions": snapshot.deletions,
        "changed_files": snapshot.changed_files,
        "commit_count": snapshot.commit_count,
        "unique_authors": snapshot.unique_authors,
        "review_count": snapshot.review_count,
        "unique_reviewers": snapshot.unique_reviewers,
        "approvals": snapshot.approvals,
        "change_requests": snapshot.change_requests,
        "is_draft": snapshot.is_draft,
        "age_hours": snapshot.age_hours,
    }

    try:
        prediction = PRRiskModelService().predict(
            features
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="The risk model has not been trained yet.",
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "pull_request_id": pull_request_id,
        **prediction,
    }

def get_pre_merge_snapshot(
    db: Session,
    pull_request_id: int,
):
    pull_request = db.scalar(
        select(PullRequest).where(
            PullRequest.id == pull_request_id
        )
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull request not found.",
        )

    merged_at = getattr(pull_request, "merged_at", None)

    snapshots_query = (
        select(PRFeatureSnapshot)
        .where(
            PRFeatureSnapshot.pull_request_id == pull_request_id,
            PRFeatureSnapshot.commit_count > 0,
            PRFeatureSnapshot.changed_files > 0,
        )
        .order_by(PRFeatureSnapshot.created_at.desc())
    )

    if merged_at is not None:
        snapshots_query = snapshots_query.where(
            PRFeatureSnapshot.created_at <= merged_at
        )

    snapshot = db.scalar(snapshots_query)

    if snapshot is None:
        raise HTTPException(
            status_code=422,
            detail="No complete pre-merge snapshot is available.",
        )

    return pull_request, snapshot