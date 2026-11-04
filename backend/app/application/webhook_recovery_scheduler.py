from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from app.application.webhook_recovery import (
    WebhookRecoveryService,
    WebhookRecoverySummary,
)

logger = logging.getLogger(__name__)


class WebhookRecoveryScheduler:
    def __init__(
        self,
        recovery_service: WebhookRecoveryService,
        *,
        interval_seconds: int,
        stale_minutes: int,
        max_attempts: int,
        batch_limit: int,
        enabled: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be at least 1")
        if stale_minutes < 1:
            raise ValueError("stale_minutes must be at least 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if batch_limit < 1:
            raise ValueError("batch_limit must be at least 1")

        self._recovery_service = recovery_service
        self._interval_seconds = interval_seconds
        self._stale_minutes = stale_minutes
        self._max_attempts = max_attempts
        self._batch_limit = batch_limit
        self._enabled = enabled
        self._clock = clock or (lambda: datetime.now(UTC))

    def run_cycle(self) -> WebhookRecoverySummary:
        stale_before = self._clock() - timedelta(minutes=self._stale_minutes)
        summary = self._recovery_service.recover(
            stale_before=stale_before,
            max_attempts=self._max_attempts,
            limit=self._batch_limit,
        )
        logger.info(
            "Automatic webhook recovery cycle completed examined=%d "
            "eligible=%d recovered=%d skipped=%d failed=%d",
            summary.examined,
            summary.eligible,
            summary.recovered,
            summary.skipped,
            summary.failed,
        )
        return summary

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        if not self._enabled:
            logger.info("Automatic webhook recovery is disabled")
            return

        logger.info(
            "Automatic webhook recovery started interval_seconds=%d "
            "stale_minutes=%d max_attempts=%d batch_limit=%d",
            self._interval_seconds,
            self._stale_minutes,
            self._max_attempts,
            self._batch_limit,
        )
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.to_thread(self.run_cycle)
                except Exception:
                    logger.exception(
                        "Automatic webhook recovery cycle failed; "
                        "the next cycle will still be attempted"
                    )

                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            logger.info("Automatic webhook recovery stopped")
