from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pull_request.models import PullRequest
from app.repository.models import Repository
from app.review.models import Review
from app.webhook.schemas import (
    PullRequestReviewWebhookPayload,
)
from app.feature.service import PRFeatureService
from app.application.outcome_evaluation import evaluate_pull_request_outcome

class ReviewWebhookService:

    def __init__(self) -> None:
        self._feature_service = PRFeatureService()

    def process(
        self,
        db: Session,
        payload: PullRequestReviewWebhookPayload,
    ) -> Review | None:

        if payload.action not in {
            "submitted",
            "edited",
            "dismissed",
        }:
            return None

        github_pr = payload.pull_request
        github_review = payload.review

        pull_request = db.scalar(
            select(PullRequest)
            .join(PullRequest.repository)
            .where(
                PullRequest.github_id == github_pr.id,
                Repository.github_id == payload.repository.id,
            )
        )

        if pull_request is None:
            raise ValueError(
                "Pull request from review webhook "
                "does not exist locally."
            )

        review = db.scalar(
            select(Review).where(
                Review.github_id == github_review.id
            )
        )

        if review is None:
            review = Review(
                github_id=github_review.id,
                pull_request_id=pull_request.id,
                reviewer_login=github_review.user.login,
                state=github_review.state,
                body=github_review.body,
                submitted_at=github_review.submitted_at,
            )
            db.add(review)
        else:
            if review.pull_request_id != pull_request.id:
                raise ValueError(
                    "GitHub review is already associated with a "
                    "different pull request."
                )
            review.pull_request_id = pull_request.id
            review.reviewer_login = github_review.user.login
            review.state = github_review.state
            review.body = github_review.body
            review.submitted_at = github_review.submitted_at

        db.commit()
        db.refresh(review)

        
        if not pull_request.merged and pull_request.state == "open":
            self._feature_service.create_snapshot(
                db=db,
                pull_request=pull_request,
            )

        evaluate_pull_request_outcome(
            db=db,
            pull_request_id=pull_request.id,
        )

        return review
