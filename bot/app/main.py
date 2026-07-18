import asyncio
import contextlib
import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import BotSettings
from app.health import write_bot_heartbeat
from app.logging_config import configure_json_logging
from app.notifications import (
    start_notification_dispatcher,
    stop_notification_dispatcher,
)
from app.community import chat_member_update, required_group_handler
from app.runtime import global_error_handler, guarded_handler, http_error_detail
from app.user_handlers import (
    API,
    bind,
    callback_menu,
    cancel_command,
    checkin_command,
    help_command,
    leaderboard_command,
    me,
    recent_command,
    redeem_points_command,
    referral_command,
    register,
    renew,
    reset_password,
    request_command,
    requests_command,
    search_command,
    start,
    text_menu,
    points_command,
)
from app.admin_handlers import (
    admin_disable,
    admin_enable,
    admin_extend,
    admin_panel,
    admin_requests,
    admin_user,
)

configure_json_logging()
logger = logging.getLogger(__name__)

# Backward-compatible public names used by safety tests and downstream imports.
_http_error_detail = http_error_detail


async def _health_heartbeat(app: Application) -> None:
    while True:
        try:
            # This verifies the Bot token and Telegram API path, not merely that
            # the companion Web API container is reachable.
            await app.bot.get_me()
            await API.health()
            write_bot_heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram Bot health probe failed")
        await asyncio.sleep(30)


def build_command_menu() -> list[BotCommand]:
    return [
        BotCommand("start", "返回首页"),
        BotCommand("help", "使用帮助"),
        BotCommand("cancel", "退出当前操作"),
        BotCommand("me", "账号与安全"),
        BotCommand("renew", "使用续期码"),
        BotCommand("reset_password", "重置登录密码"),
        BotCommand("checkin", "每日签到"),
        BotCommand("points", "积分与兑换"),
        BotCommand("referral", "好友邀请"),
        BotCommand("recent", "查看最近收听"),
        BotCommand("search", "搜索有声书"),
        BotCommand("request", "提交内容请求"),
        BotCommand("requests", "查看内容请求"),
    ]


async def setup_bot(app: Application) -> None:
    await app.bot.set_my_commands(build_command_menu())
    await start_notification_dispatcher(app, API)
    await app.bot.get_me()
    await API.health()
    write_bot_heartbeat()
    app.bot_data["health_task"] = asyncio.create_task(_health_heartbeat(app))


async def shutdown_bot(app: Application) -> None:
    health_task = app.bot_data.pop("health_task", None)
    if health_task is not None:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task
    await stop_notification_dispatcher(API)


def build_application(settings: BotSettings | None = None) -> Application:
    settings = settings or BotSettings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(setup_bot)
        .post_shutdown(shutdown_bot)
        .build()
    )
    user_handlers = (
        ("start", start),
        ("help", help_command),
        ("cancel", cancel_command),
        ("bind", bind),
        ("register", register),
        ("me", me),
        ("renew", renew),
        ("reset_password", reset_password),
        ("checkin", checkin_command),
        ("points", points_command),
        ("redeem_points", redeem_points_command),
        ("referral", referral_command),
        ("request", request_command),
        ("requests", requests_command),
        ("recent", recent_command),
        ("search", search_command),
        ("leaderboard", leaderboard_command),
    )
    for command, handler in user_handlers:
        app.add_handler(
            CommandHandler(
                command, guarded_handler(required_group_handler(handler, API))
            )
        )
    for command, handler in (
        ("admin", admin_panel),
        ("admin_user", admin_user),
        ("admin_disable", admin_disable),
        ("admin_enable", admin_enable),
        ("admin_extend", admin_extend),
        ("admin_requests", admin_requests),
    ):
        app.add_handler(CommandHandler(command, guarded_handler(handler)))
    app.add_handler(
        CallbackQueryHandler(
            guarded_handler(required_group_handler(callback_menu, API))
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            guarded_handler(required_group_handler(text_menu, API)),
        )
    )

    async def membership_update(update, context):
        await chat_member_update(update, context, API)

    app.add_handler(ChatMemberHandler(membership_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_error_handler(global_error_handler)
    return app


def main() -> None:
    app = build_application()
    logger.info("MoYin Telegram bot starting in polling mode")
    app.run_polling(allowed_updates=["message", "callback_query", "chat_member"])


if __name__ == "__main__":
    main()
