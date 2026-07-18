import asyncio
import fcntl
import logging
import os
import time
from pathlib import Path
from typing import TextIO

from app.config import Settings
from app.maintenance import run_maintenance
from app.worker_health import write_worker_health_state

logger = logging.getLogger(__name__)


def acquire_scheduler_lock(path_value: str) -> TextIO | None:
    """Acquire the deployment-wide scheduler lock without blocking the API."""
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def release_scheduler_lock(handle: TextIO) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class Scheduler:
    """Run portal maintenance tasks inside the API process with leader locking."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.settings.scheduler_enabled:
            logger.info("scheduler_disabled")
            return
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="moyin-scheduler")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        await task
        self._task = None

    async def _wait(self, seconds: int) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _run(self) -> None:
        retry_seconds = min(self.settings.scheduler_interval_seconds, 30)
        while not self._stop_event.is_set():
            lock = acquire_scheduler_lock(self.settings.scheduler_lock_path)
            if lock is None:
                logger.info("scheduler_lock_held_by_another_process")
                await self._wait(retry_seconds)
                continue
            try:
                logger.info(
                    "scheduler_leader_started",
                    extra={"interval_seconds": self.settings.scheduler_interval_seconds},
                )
                await self._run_as_leader()
            finally:
                release_scheduler_lock(lock)

    async def _run_as_leader(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = await run_maintenance(self.settings)
                write_worker_health_state(
                    last_success=int(time.time()),
                    last_error=None,
                    result=result,
                )
                logger.info("scheduler_tick_completed", extra={"result": result})
            except Exception as exc:  # noqa: BLE001 - a failed tick must not stop the API
                error = f"{type(exc).__name__}: {exc}"[:2000]
                write_worker_health_state(last_error=error)
                logger.exception("scheduler_tick_failed")
            await self._wait(self.settings.scheduler_interval_seconds)
