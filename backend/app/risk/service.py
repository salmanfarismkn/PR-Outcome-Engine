from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.service import AnalysisService
from app.risk.engine import RiskEngine
from app.risk.models import RiskAssessment
from app.risk.schemas import (
    RiskAssessmentResponse,
    RiskAssessmentSummary,
)


class RiskService:

    def __init__(self) -> None:
        self._analysis_service = AnalysisService()
        self._risk_engine = RiskEngine()

    def analyze_pull_request(
        self,
        db: Session,
        pull_request_id: int,
    ) -> RiskAssessmentResponse:

        metrics = self._analysis_service.calculate_metrics(
            db=db,
            pull_request_id=pull_request_id,
        )

        risk = self._risk_engine.calculate(
            pull_request_id=pull_request_id,
            metrics=metrics,
        )

        assessment = RiskAssessment(
            pull_request_id=pull_request_id,
            score=risk.score,
            level=risk.level,
            recommendation=risk.recommendation,
            metrics=risk.metrics.model_dump(),
            categories=[
                category.model_dump()
                for category in risk.categories
            ],
            factors=[
                factor.model_dump()
                for factor in risk.factors
            ],
        )

        db.add(assessment)
        db.commit()
        db.refresh(assessment)

        return RiskAssessmentResponse(
            assessment_id=assessment.id,
            created_at=assessment.created_at,
            pull_request_id=risk.pull_request_id,
            score=risk.score,
            level=risk.level,
            recommendation=risk.recommendation,
            categories=risk.categories,
            factors=risk.factors,
            metrics=risk.metrics,
        )

    def get_latest_assessment(
        self,
        db: Session,
        pull_request_id: int,
    ) -> RiskAssessmentResponse | None:

        assessment = db.scalar(
            select(RiskAssessment)
            .where(
                RiskAssessment.pull_request_id
                == pull_request_id
            )
            .order_by(
                RiskAssessment.created_at.desc(),
                RiskAssessment.id.desc(),
            )
            .limit(1)
        )

        if assessment is None:
            return None

        return RiskAssessmentResponse(
            assessment_id=assessment.id,
            created_at=assessment.created_at,
            pull_request_id=assessment.pull_request_id,
            score=assessment.score,
            level=assessment.level,
            recommendation=assessment.recommendation,
            categories=[
                category
                for category in assessment.categories
            ],
            factors=[
                factor
                for factor in assessment.factors
            ],
            metrics=assessment.metrics,
        )

    def get_history(
        self,
        db: Session,
        pull_request_id: int,
    ) -> list[RiskAssessmentSummary]:

        assessments = list(
            db.scalars(
                select(RiskAssessment)
                .where(
                    RiskAssessment.pull_request_id
                    == pull_request_id
                )
                .order_by(
                    RiskAssessment.created_at.desc()
                )
            )
        )

        return [
            RiskAssessmentSummary(
                assessment_id=assessment.id,
                pull_request_id=assessment.pull_request_id,
                score=assessment.score,
                level=assessment.level,
                created_at=assessment.created_at,
            )
            for assessment in assessments
        ]