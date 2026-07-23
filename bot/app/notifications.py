import asyncio
import logging
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import Application

from app.config import BotSettings
from app.internal_api import InternalApi

logger = logging.getLogger(__name__)
_stop_event: asyncio.Event | None = None
_task: asyncio.Task[None] | None = None


def notification_reply_markup(item: dict[str, object]) -> InlineKeyboardMarkup | None:
    kind = item.get("kind")
    if kind == "media_request_status":
        url = BotSettings().portal_public_url.rstrip("/") + "/dashboard?tab=requests"
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🌐 Web 端查看工单", url=url)]]
        )
    if kind != "media_request_admin":
        return None
    parts = str(item.get("dedupeKey") or "").split(":")
    if len(parts) < 3 or not parts[1]:
        return None
    request_id = parts[1]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 接受请求", callback_data=f"adm_req:accepted:{request_id}"),
                InlineKeyboardButton("💬 回复工单", callback_data=f"adm_req_reply:{request_id}"),
            ],
            [InlineKeyboardButton("🏁 结束工单", callback_data=f"adm_req:available:{request_id}")],
        ]
    )


def _retry_seconds(exc: RetryAfter) -> int:
    value = exc.retry_after
    if isinstance(value, timedelta):
        return max(1, int(value.total_seconds()))
    return max(1, int(value))


def next_poll_delay(
    current: int, *, base_seconds: int, had_work: bool, failed: bool
) -> int:
    if had_work:
        return base_seconds
    return min(60, max(base_seconds, current * 2))


async def _dispatch_loop(app: Application, api: InternalApi, stop: asyncio.Event) -> None:
    poll_seconds = BotSettings().telegram_notification_poll_seconds
    delay = poll_seconds
    while not stop.is_set():
        had_work = False
        failed = False
        try:
            notifications = await api.claim_notifications(limit=10)
            had_work = bool(notifications)
            for item in notifications:
                notification_id = str(item.get("id") or "")
                if not notification_id:
                    continue
                try:
                    await app.bot.send_message(
                        chat_id=str(item.get("telegramId") or ""),
                        text=str(item.get("message") or ""),
                        reply_markup=notification_reply_markup(item),
                    )
                    await api.acknowledge_notification(notification_id, success=True)
                except RetryAfter as exc:
                    await api.acknowledge_notification(
                        notification_id,
                        success=False,
                        error="telegram rate limited delivery",
                        retry_after_seconds=_retry_seconds(exc),
                    )
                except (Forbidden, BadRequest) as exc:
                    await api.acknowledge_notification(
                        notification_id,
                        success=False,
                        error=str(exc),
                        retryable=False,
                    )
                except TelegramError as exc:
                    await api.acknowledge_notification(
                        notification_id,
                        success=False,
                        error=str(exc),
                    )
        except Exception:
            failed = True
            logger.exception("Telegram notification dispatcher iteration failed")
        delay = next_poll_delay(
            delay, base_seconds=poll_seconds, had_work=had_work, failed=failed
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass


async def start_notification_dispatcher(app: Application, api: InternalApi) -> None:
    global _stop_event, _task
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(
        _dispatch_loop(app, api, _stop_event),
        name="telegram-notification-dispatcher",
    )


async def stop_notification_dispatcher(api: InternalApi) -> None:
    global _stop_event, _task
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _stop_event = None
    _task = None
    await api.close()
