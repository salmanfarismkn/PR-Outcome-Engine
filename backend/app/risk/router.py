from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.pull_request.models import PullRequest
from app.risk.schemas import (
    RiskAssessmentResponse,
    RiskAssessmentSummary,
)
from app.risk.service import RiskService
from app.api.dependencies import require_admin_access


router = APIRouter(
    prefix="/risk",
    tags=["Risk Analysis"],
)

risk_service = RiskService()


@router.post(
    "/pull-request/{pull_request_id}/analyze",
    response_model=RiskAssessmentResponse,
    status_code=HTTPStatus.OK,
    dependencies=[Depends(require_admin_access)],
)
def analyze_pull_request(
    pull_request_id: int,
    db: Session = Depends(get_db),
) -> RiskAssessmentResponse:

    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Pull request not found.",
        )

    return risk_service.analyze_pull_request(
        db=db,
        pull_request_id=pull_request_id,
    )


@router.get(
    "/pull-request/{pull_request_id}",
    response_model=RiskAssessmentResponse,
)
def get_latest_risk(
    pull_request_id: int,
    db: Session = Depends(get_db),
) -> RiskAssessmentResponse:

    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Pull request not found.",
        )

    assessment = risk_service.get_latest_assessment(
        db=db,
        pull_request_id=pull_request_id,
    )

    if assessment is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="No risk assessment exists for this pull request.",
        )

    return assessment


@router.get(
    "/pull-request/{pull_request_id}/history",
    response_model=list[RiskAssessmentSummary],
)
def get_risk_history(
    pull_request_id: int,
    db: Session = Depends(get_db),
) -> list[RiskAssessmentSummary]:

    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Pull request not found.",
        )

    return risk_service.get_history(
        db=db,
        pull_request_id=pull_request_id,
    )