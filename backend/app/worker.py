"""One-shot compatibility entry point for manual scheduled maintenance."""

import argparse
import asyncio
import time

from app.config import Settings
from app.db import create_db_and_tables, get_engine
from app.maintenance import run_maintenance
from app.scheduler import acquire_scheduler_lock, release_scheduler_lock
from app.worker_health import write_worker_health_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Audiobookshelf portal scheduled maintenance")
    parser.add_argument("--once", action="store_true", help="retained for command compatibility")
    parser.parse_args()

    settings = Settings()
    create_db_and_tables(get_engine(settings.database_url))
    lock = acquire_scheduler_lock(settings.scheduler_lock_path)
    if lock is None:
        raise SystemExit("scheduled maintenance is already running")
    try:
        result = asyncio.run(run_maintenance(settings))
        write_worker_health_state(last_success=int(time.time()), last_error=None, result=result)
        print(result)
    finally:
        release_scheduler_lock(lock)


if __name__ == "__main__":
    main()
