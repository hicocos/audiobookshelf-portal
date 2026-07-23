import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from app.config import BotSettings
from app.handlers import SimpleRateLimiter, dashboard_url
from app.logging_config import update_id_context

logger = logging.getLogger(__name__)
REGISTER_LIMITER = SimpleRateLimiter(max_calls=3, window_seconds=600)
COMMAND_LIMITER = SimpleRateLimiter(max_calls=30, window_seconds=60)
BotHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


async def ensure_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    if chat is not None and chat.type == ChatType.PRIVATE:
        return True
    message = update.effective_message
    if message is not None:
        await message.reply_text("为保护邀请码、绑定码和账号信息，请私聊 Bot 使用此功能。")
    return False


def telegram_identity(update: Update) -> tuple[int, str | None]:
    user = update.effective_user
    if user is None:
        raise RuntimeError("Missing Telegram user")
    return user.id, user.username


def web_console_url() -> str:
    return dashboard_url(BotSettings().portal_public_url)


def guarded_handler(handler: BotHandler) -> BotHandler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        token = update_id_context.set(update.update_id)
        try:
            if not await ensure_private_chat(update):
                return
            telegram_id, _username = telegram_identity(update)
            if not COMMAND_LIMITER.allow(str(telegram_id)):
                message = update.effective_message
                if message is not None:
                    await message.reply_text("操作过于频繁，请稍后再试。")
                return
            await handler(update, context)
        finally:
            update_id_context.reset(token)

    return wrapped


def http_error_detail(exc: httpx.HTTPStatusError, fallback: str) -> str:
    try:
        payload = exc.response.json()
    except (json.JSONDecodeError, ValueError):
        logger.debug("Bot API error response is not JSON status_code=%s", exc.response.status_code)
        return fallback
    if not isinstance(payload, dict):
        return fallback
    detail = payload.get("detail")
    if not isinstance(detail, str):
        return fallback
    known_messages = {
        "Invalid or expired bind code": "绑定码无效或已过期，请重新生成。",
        "Telegram account is already bound": "这个 Telegram 账号已经绑定。",
        "Account is disabled": "账号已停用，请联系管理员。",
        "Account is expired": "账号已到期，请先完成续期。",
    }
    return known_messages.get(detail, detail if any("\u4e00" <= char <= "\u9fff" for char in detail) else fallback)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    update_id = getattr(update, "update_id", "unknown")
    token = update_id_context.set(update_id)
    try:
        logger.error(
            "Unhandled bot error",
            exc_info=(
                (type(context.error), context.error, context.error.__traceback__)
                if context.error
                else None
            ),
        )
        message = getattr(update, "effective_message", None)
        if message is not None:
            try:
                await message.reply_text(
                    "请求失败，请稍后重试。若持续失败，请联系管理员并提供此请求编号：%s"
                    % update_id
                )
            except Exception:
                logger.exception("Failed to send safe error response")
    finally:
        update_id_context.reset(token)
