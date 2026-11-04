from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main  # noqa: F401
from app.application.webhook_recovery import WebhookRecoveryService
from app.application.webhook_recovery_scheduler import WebhookRecoveryScheduler
from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run automatic periodic stale webhook recovery.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=settings.webhook_recovery_interval_seconds,
        help="Seconds between recovery cycles.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=settings.webhook_recovery_stale_minutes,
        help="Minimum event age in minutes.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=settings.webhook_recovery_max_attempts,
        help="Maximum recovery attempts per event.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.webhook_recovery_batch_limit,
        help="Maximum events per cycle.",
    )
    args = parser.parse_args()
    if args.interval_seconds < 1:
        parser.error("--interval-seconds must be at least 1.")
    if args.stale_minutes < 1:
        parser.error("--stale-minutes must be at least 1.")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1.")
    if args.limit < 1:
        parser.error("--limit must be at least 1.")
    return args


async def run(args: argparse.Namespace) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            signal.signal(signum, lambda _signum, _frame: stop_event.set())

    scheduler = WebhookRecoveryScheduler(
        WebhookRecoveryService(SessionLocal),
        interval_seconds=args.interval_seconds,
        stale_minutes=args.stale_minutes,
        max_attempts=args.max_attempts,
        batch_limit=args.limit,
        enabled=True,
    )
    await scheduler.run_forever(stop_event)


def main() -> int:
    args = parse_args()
    if not settings.webhook_recovery_enabled:
        logger.error(
            "Automatic webhook recovery is disabled. Set "
            "WEBHOOK_RECOVERY_ENABLED=true before starting this process."
        )
        return 2
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Automatic webhook recovery interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
