from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.check.models import CheckRun
from app.outcome.models import PullRequestOutcome
from app.pull_request.models import PullRequest
from app.outcome.revert_models import RevertEvent


FAILED_CONCLUSIONS = {
    "failure",
    "timed_out",
    "action_required",
}


class OutcomeEvaluator:

    def evaluate(
        self,
        db: Session,
        pull_request: PullRequest,
    ) -> PullRequestOutcome:

        print("[webhook-debug] outcome: existing outcome query started", flush=True)
        outcome = (
            db.query(PullRequestOutcome)
            .filter(
                PullRequestOutcome.pull_request_id == pull_request.id
            )
            .first()
        )
        print(
            "[webhook-debug] outcome: existing outcome query returned; "
            f"found={outcome is not None}",
            flush=True,
        )

        if outcome is None:
            outcome = PullRequestOutcome(
                pull_request_id=pull_request.id,
            )
            db.add(outcome)

        merged = getattr(pull_request, "merged", False)

        merged_at = getattr(
            pull_request,
            "merged_at",
            None,
        )

        state = getattr(
            pull_request,
            "state",
            None,
        )

        # -----------------------------------------
        # Lifecycle
        # -----------------------------------------

        if merged:
            outcome.lifecycle_status = "merged"
            outcome.merged_at = merged_at

        elif state == "closed":
            outcome.lifecycle_status = "closed"

        else:
            outcome.lifecycle_status = "pending"

        # -----------------------------------------
        # CI evidence
        # -----------------------------------------

        print("[webhook-debug] outcome: checks query started", flush=True)
        checks = (
            db.query(CheckRun)
            .filter(
                CheckRun.pull_request_id == pull_request.id
            )
            .all()
        )
        print(
            "[webhook-debug] outcome: checks query returned; "
            f"count={len(checks)}",
            flush=True,
        )

        current_head_checks = [
            check
            for check in checks
            if pull_request.head_sha
            and check.head_sha == pull_request.head_sha
        ]
        failed_checks = [
            check
            for check in current_head_checks
            if check.status == "completed"
            and check.conclusion in FAILED_CONCLUSIONS
        ]
        all_checks_succeeded = bool(current_head_checks) and all(
            check.status == "completed"
            and check.conclusion == "success"
            for check in current_head_checks
        )
        # -----------------------------------------
        # Revert evidence
        # -----------------------------------------

        print("[webhook-debug] outcome: revert query started", flush=True)
        revert_event = (
            db.query(RevertEvent)
            .filter(
                RevertEvent.pull_request_id == pull_request.id
            )
            .first()
        )
        print("[webhook-debug] outcome: revert query returned", flush=True)

        was_reverted = revert_event is not None
        # -----------------------------------------
        # Quality classification
        # -----------------------------------------

        if not merged:
            outcome.outcome = "uncertain"
            outcome.reason = "PR has not been merged"

        elif was_reverted:
            outcome.outcome = "problematic"
            outcome.reason = "PR was later reverted"

        elif failed_checks:
            outcome.outcome = "problematic"
            outcome.reason = (
                "Current PR head has a completed failing CI check"
            )

        elif all_checks_succeeded:
            outcome.outcome = "healthy"
            outcome.reason = (
                "Current PR head has completed successful CI checks "
                "and no verified revert"
            )

        else:
            outcome.outcome = "uncertain"
            if not pull_request.head_sha:
                outcome.reason = "Current PR head SHA is unavailable"
            elif not current_head_checks:
                outcome.reason = (
                    "No CI evidence is recorded for the current PR head"
                )
            else:
                outcome.reason = (
                    "Current PR head does not have exclusively completed "
                    "successful CI checks"
                )

        outcome.observed_at = datetime.now(timezone.utc)

        db.add(outcome)
        print("[webhook-debug] outcome: commit started", flush=True)
        db.commit()
        print("[webhook-debug] outcome: commit returned", flush=True)
        print("[webhook-debug] outcome: refresh started", flush=True)
        db.refresh(outcome)
        print("[webhook-debug] outcome: refresh returned", flush=True)

        return outcome