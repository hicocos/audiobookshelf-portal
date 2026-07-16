import asyncio
import json
import time
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.abs_client import AudiobookshelfClient
from app.config import Settings
from app.db import get_engine
from app.services.reconciliation import process_reconciliation_jobs


def _state_path() -> Path:
    return Path(Settings().worker_health_state_path)


def write_worker_health_state(
    *,
    last_success: int | None = None,
    last_error: str | None = None,
    result: dict[str, int] | None = None,
) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    try:
        previous = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    state = {
        **previous,
        "lastAttempt": int(time.time()),
        "lastSuccess": last_success if last_success is not None else previous.get("lastSuccess"),
        "lastError": last_error,
        "result": result if result is not None else previous.get("result"),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    temporary.replace(path)


def worker_health_status(*, max_age_seconds: int | None = None) -> dict[str, Any]:
    if max_age_seconds is None:
        max_age_seconds = Settings().worker_health_max_age_seconds
    try:
        state = json.loads(_state_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"healthy": False, "reason": "missing health state"}
    last_success = state.get("lastSuccess")
    if not isinstance(last_success, int):
        return {"healthy": False, "reason": "worker has not succeeded"}
    lag = max(0, int(time.time()) - last_success)
    if lag > max_age_seconds:
        return {"healthy": False, "reason": "worker success is stale", "lagSeconds": lag}
    return {"healthy": True, "lagSeconds": lag, "lastError": state.get("lastError")}


def check_worker_health() -> None:
    status = worker_health_status()
    print(json.dumps(status, ensure_ascii=False))
    raise SystemExit(0 if status["healthy"] else 1)


def retry_job(job_id: str) -> None:
    settings = Settings()

    async def _run() -> dict[str, int]:
        with Session(get_engine(settings.database_url)) as session:
            async with AudiobookshelfClient(
                settings.audiobookshelf_url,
                settings.audiobookshelf_admin_token,
            ) as abs_client:
                return await process_reconciliation_jobs(
                    session,
                    abs_client,
                    limit=1,
                    job_id=job_id,
                )

    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("processed") == 1 else 1)
