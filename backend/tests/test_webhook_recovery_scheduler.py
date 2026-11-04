import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.application.webhook_recovery_scheduler import WebhookRecoveryScheduler


def _summary():
    return SimpleNamespace(
        examined=1,
        eligible=1,
        recovered=1,
        skipped=0,
        failed=0,
    )


def test_disabled_scheduler_does_not_run() -> None:
    service = SimpleNamespace(recover=lambda **_kwargs: pytest.fail("unexpected run"))
    scheduler = WebhookRecoveryScheduler(
        service,
        interval_seconds=10,
        stale_minutes=15,
        max_attempts=3,
        batch_limit=5,
        enabled=False,
    )

    asyncio.run(scheduler.run_forever(asyncio.Event()))


def test_cycle_reuses_recovery_service_and_configuration() -> None:
    calls = []
    service = SimpleNamespace(
        recover=lambda **kwargs: calls.append(kwargs) or _summary()
    )
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    scheduler = WebhookRecoveryScheduler(
        service,
        interval_seconds=10,
        stale_minutes=15,
        max_attempts=3,
        batch_limit=7,
        clock=lambda: now,
    )

    scheduler.run_cycle()

    assert calls == [
        {
            "stale_before": datetime(2026, 11, 1, 11, 45, tzinfo=UTC),
            "max_attempts": 3,
            "limit": 7,
        }
    ]


@pytest.mark.asyncio
async def test_failure_does_not_disable_later_cycle(monkeypatch) -> None:
    calls = 0

    def recover(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database unavailable")
        return _summary()

    service = SimpleNamespace(recover=recover)
    scheduler = WebhookRecoveryScheduler(
        service,
        interval_seconds=10,
        stale_minutes=15,
        max_attempts=3,
        batch_limit=5,
    )
    waits = 0

    async def fake_to_thread(function):
        return function()

    async def fake_wait_for(awaitable, timeout):
        nonlocal waits
        awaitable.close()
        waits += 1
        if waits == 2:
            stop_event.set()
        if waits == 1:
            raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    stop_event = asyncio.Event()

    await scheduler.run_forever(stop_event)

    assert calls == 2


@pytest.mark.asyncio
async def test_scheduler_does_not_overlap_cycles(monkeypatch) -> None:
    active = 0
    maximum_active = 0
    calls = 0

    def recover(**_kwargs):
        nonlocal active, maximum_active, calls
        calls += 1
        active += 1
        maximum_active = max(maximum_active, active)
        active -= 1
        return _summary()

    scheduler = WebhookRecoveryScheduler(
        SimpleNamespace(recover=recover),
        interval_seconds=1,
        stale_minutes=15,
        max_attempts=3,
        batch_limit=5,
    )

    async def fake_to_thread(function):
        return function()

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        stop_event.set()

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    stop_event = asyncio.Event()

    await scheduler.run_forever(stop_event)

    assert calls == 1
    assert maximum_active == 1
