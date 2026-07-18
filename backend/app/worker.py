import argparse
import asyncio
import time

from sqlmodel import Session

from app.abs_client import AudiobookshelfClient
from app.config import Settings
from app.db import create_db_and_tables, get_engine
from app.services.expiry import sync_expired_users
from app.services.community import enforce_group_grace_periods
from app.services.data_retention import apply_data_retention
from app.services.inactivity import sync_inactive_users
from app.services.reconciliation import process_reconciliation_jobs
from app.services.referrals import settle_pending_referrals
from app.services.settings import get_public_settings, update_public_settings
from app.services.telegram_notifications import enqueue_lifecycle_notifications
from app.worker_health import write_worker_health_state


async def run_once() -> dict[str, int]:
    settings = Settings()
    engine = get_engine(settings.database_url)
    with Session(engine) as session:
        async with AudiobookshelfClient(
            settings.audiobookshelf_url,
            settings.audiobookshelf_admin_token,
        ) as abs_client:
            reconciliation = await process_reconciliation_jobs(session, abs_client)
            referrals_settled = settle_pending_referrals(session)
            public_settings = get_public_settings(session)
            operations = (
                public_settings.get("operations")
                if isinstance(public_settings.get("operations"), dict)
                else {}
            )
            inactive = await sync_inactive_users(
                session,
                abs_client,
                enabled=bool(operations.get("inactivityAutoDisable")),
                inactive_days=int(operations.get("inactiveDays") or 30),
                new_user_grace_days=int(operations.get("newUserGraceDays") or 7),
                actor="worker",
                dry_run=False,
            )
            if inactive.get("enabled"):
                update_public_settings(
                    session,
                    {
                        "operations": {
                            **operations,
                            "lastInactivityCheckAt": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                            "lastInactivityDisabled": inactive.get("disabled", 0),
                        }
                    },
                )
            telegram_settings = public_settings.get("telegram")
            telegram_settings = telegram_settings if isinstance(telegram_settings, dict) else {}
            group_enforcement = (
                await enforce_group_grace_periods(session, abs_client)
                if telegram_settings.get("groupMembershipEnabled")
                else {"checked": 0, "disabled": 0, "failed": 0}
            )
            notifications = enqueue_lifecycle_notifications(
                session, public_settings=public_settings
            )
            expired = await sync_expired_users(session, abs_client)
            retention = apply_data_retention(session)
            return {
                "reconciliationProcessed": reconciliation.get("processed", 0),
                "reconciliationFailed": reconciliation.get("failed", 0),
                "referralsSettled": referrals_settled,
                "expiredDisabled": expired.get("disabled", 0),
                "inactiveDisabled": inactive.get("disabled", 0),
                "expiryNotificationsQueued": notifications.get("expiryQueued", 0),
                "groupMembershipDisabled": group_enforcement.get("disabled", 0),
                "groupMembershipFailed": group_enforcement.get("failed", 0),
                "retentionDeleted": sum(retention.values()),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audiobookshelf portal background worker")
    parser.add_argument("--once", action="store_true", help="run one expiry sync and exit")
    parser.add_argument("--interval", type=int, default=600, help="seconds between expiry sync runs")
    args = parser.parse_args()

    settings = Settings()
    create_db_and_tables(get_engine(settings.database_url))

    if args.once:
        result = asyncio.run(run_once())
        write_worker_health_state(last_success=int(time.time()), last_error=None, result=result)
        print(result)
        return

    while True:
        try:
            result = asyncio.run(run_once())
            write_worker_health_state(last_success=int(time.time()), last_error=None, result=result)
            print(result, flush=True)
        except Exception as exc:  # noqa: BLE001 — never let one bad tick crash the loop
            write_worker_health_state(last_error=f"{type(exc).__name__}: {exc}"[:2000])
            print({"error": repr(exc)}, flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
