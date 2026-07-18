import asyncio

from app.config import Settings
from app.scheduler import (
    Scheduler,
    acquire_scheduler_lock,
    release_scheduler_lock,
)


def _settings(tmp_path, **values) -> Settings:
    config = {
        "SCHEDULER_ENABLED": True,
        "SCHEDULER_INTERVAL_SECONDS": 60,
        "SCHEDULER_LOCK_PATH": str(tmp_path / "scheduler.lock"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'portal.db'}",
    }
    config.update(values)
    return Settings(**config)


def test_scheduler_lock_allows_only_one_process(tmp_path):
    path = str(tmp_path / "scheduler.lock")
    first = acquire_scheduler_lock(path)
    assert first is not None
    assert acquire_scheduler_lock(path) is None
    release_scheduler_lock(first)

    replacement = acquire_scheduler_lock(path)
    assert replacement is not None
    release_scheduler_lock(replacement)


def test_disabled_scheduler_does_not_create_a_task(tmp_path):
    async def exercise() -> None:
        scheduler = Scheduler(_settings(tmp_path, SCHEDULER_ENABLED=False))
        scheduler.start()
        assert scheduler.running is False
        await scheduler.stop()

    asyncio.run(exercise())


def test_scheduler_runs_immediately_and_stops_cleanly(monkeypatch, tmp_path):
    async def exercise() -> None:
        completed = asyncio.Event()
        health_states: list[dict] = []

        async def fake_run_once(_settings):
            return {"expiredDisabled": 2}

        def fake_write_health(**state):
            health_states.append(state)
            completed.set()

        monkeypatch.setattr("app.scheduler.run_maintenance", fake_run_once)
        monkeypatch.setattr("app.scheduler.write_worker_health_state", fake_write_health)

        scheduler = Scheduler(_settings(tmp_path))
        scheduler.start()
        await asyncio.wait_for(completed.wait(), timeout=1)
        assert scheduler.running is True
        await scheduler.stop()
        assert scheduler.running is False
        assert health_states[0]["result"] == {"expiredDisabled": 2}
        assert health_states[0]["last_error"] is None

    asyncio.run(exercise())


def test_scheduler_records_tick_errors_without_crashing(monkeypatch, tmp_path):
    async def exercise() -> None:
        recorded = asyncio.Event()
        health_states: list[dict] = []

        async def failing_run_once(_settings):
            raise RuntimeError("temporary upstream failure")

        def fake_write_health(**state):
            health_states.append(state)
            recorded.set()

        monkeypatch.setattr("app.scheduler.run_maintenance", failing_run_once)
        monkeypatch.setattr("app.scheduler.write_worker_health_state", fake_write_health)

        scheduler = Scheduler(_settings(tmp_path))
        scheduler.start()
        await asyncio.wait_for(recorded.wait(), timeout=1)
        await scheduler.stop()
        assert health_states == [{"last_error": "RuntimeError: temporary upstream failure"}]

    asyncio.run(exercise())
