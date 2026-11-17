from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401
from app.application.webhook_recovery import (
    WebhookRecoveryService,
    WebhookRecoverySummary,
)
from app.db.session import SessionLocal

DEFAULT_STALE_MINUTES = 15
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LIMIT = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or recover stale webhook deliveries.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Claim and replay eligible events; dry-run is the default.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=DEFAULT_STALE_MINUTES,
        help=f"Minimum age in minutes (default: {DEFAULT_STALE_MINUTES}).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"Maximum recovery attempts (default: {DEFAULT_MAX_ATTEMPTS}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum events to inspect or recover (default: {DEFAULT_LIMIT}).",
    )
    args = parser.parse_args()
    if args.stale_minutes < 1:
        parser.error("--stale-minutes must be at least 1.")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1.")
    if args.limit < 1:
        parser.error("--limit must be at least 1.")
    return args


def main() -> int:
    args = parse_args()
    stale_before = datetime.now(UTC) - timedelta(
        minutes=args.stale_minutes
    )

    try:
        if args.execute:
            summary = WebhookRecoveryService(SessionLocal).recover(
                stale_before=stale_before,
                max_attempts=args.max_attempts,
                limit=args.limit,
            )
        else:
            service = WebhookRecoveryService(SessionLocal)
            with SessionLocal() as db:
                candidates = service.list_stale_events(
                    db,
                    stale_before,
                    args.max_attempts,
                    args.limit,
                )
            summary = WebhookRecoverySummary(
                examined=len(candidates),
                eligible=len(candidates),
                events=candidates,
            )
        with SessionLocal() as db:
            metrics = WebhookRecoveryService(SessionLocal).get_operational_metrics(
                db,
                stale_before,
                args.max_attempts,
                recovery_attempts=summary.examined,
            )
        for candidate in summary.events:
            logger.info(
                "Webhook event id=%s delivery=%s type=%s status=%s "
                "age_minutes=%.1f attempts=%s",
                candidate.event_id,
                candidate.delivery_id,
                candidate.event_type,
                candidate.status,
                candidate.age.total_seconds() / 60,
                candidate.attempt_count,
            )
        logger.info(
            "Webhook metrics: total=%d received=%d processing=%d pending=%d "
            "processed=%d failed=%d exhausted=%d eligible=%d "
            "oldest_unrecovered_age_minutes=%s recovery_attempts=%d",
            metrics.total,
            metrics.received,
            metrics.processing,
            metrics.pending,
            metrics.processed,
            metrics.failed,
            metrics.exhausted,
            metrics.eligible_for_recovery,
            (
                f"{metrics.oldest_unrecovered_age.total_seconds() / 60:.1f}"
                if metrics.oldest_unrecovered_age is not None
                else "none"
            ),
            metrics.recovery_attempts,
        )
    except Exception:
        logger.exception("Webhook recovery command failed")
        return 2

    logger.info(
        "Webhook recovery summary: examined=%d eligible=%d recovered=%d "
        "skipped=%d failed=%d mode=%s",
        summary.examined,
        summary.eligible,
        summary.recovered,
        summary.skipped,
        summary.failed,
        "execute" if args.execute else "dry-run",
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
