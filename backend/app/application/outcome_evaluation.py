from sqlalchemy.orm import Session

from app.outcome.service import OutcomeEvaluator
from app.pull_request.models import PullRequest


def evaluate_pull_request_outcome(
    db: Session,
    pull_request_id: int,
):
    print(
        "[webhook-debug] outcome helper: pull request query started; "
        f"id={pull_request_id}",
        flush=True,
    )
    pull_request = (
        db.query(PullRequest)
        .filter(PullRequest.id == pull_request_id)
        .first()
    )
    print(
        "[webhook-debug] outcome helper: pull request query returned; "
        f"found={pull_request is not None}",
        flush=True,
    )

    if pull_request is None:
        return None

    evaluator = OutcomeEvaluator()

    print("[webhook-debug] outcome helper: evaluation started", flush=True)
    result = evaluator.evaluate(
        db=db,
        pull_request=pull_request,
    )
    print("[webhook-debug] outcome helper: evaluation returned", flush=True)
    return result