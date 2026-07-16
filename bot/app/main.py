import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from telegram import BotCommand, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import BotSettings
from app.handlers import (
    SimpleRateLimiter,
    build_cancel_keyboard,
    build_panel_inline_keyboard,
    build_register_confirm_keyboard,
    dashboard_url,
    format_bind_prompt,
    format_bind_success,
    format_help,
    format_library_summary,
    format_me,
    format_open,
    format_panel,
    format_register_confirm_prompt,
    format_register_invite_prompt,
    format_register_success,
    format_register_username_prompt,
    format_search_results,
    parse_bind_code,
    parse_register_args,
)
from app.internal_api import InternalApi
from app.logging_config import configure_json_logging, update_id_context

configure_json_logging()
logger = logging.getLogger(__name__)
REGISTER_LIMITER = SimpleRateLimiter(max_calls=3, window_seconds=600)
COMMAND_LIMITER = SimpleRateLimiter(max_calls=30, window_seconds=60)
FLOW_KEY = "flow"
FLOW_REGISTER_INVITE = "register_invite"
FLOW_REGISTER_USERNAME = "register_username"
FLOW_REGISTER_CONFIRM = "register_confirm"
FLOW_BIND_CODE = "bind_code"


BotHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


async def ensure_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    if chat is not None and chat.type == ChatType.PRIVATE:
        return True
    message = update.effective_message
    if message is not None:
        await message.reply_text("为保护邀请码、绑定码和账号信息，请私聊 Bot 使用此功能。")
    return False


def guarded_handler(handler: BotHandler) -> BotHandler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        token = update_id_context.set(update.update_id)
        try:
            if not await ensure_private_chat(update):
                return
            telegram_id, _username = _telegram_identity(update)
            if not _allow_command(telegram_id):
                message = update.effective_message
                if message is not None:
                    await message.reply_text("操作过于频繁，请稍后再试。")
                return
            await handler(update, context)
        finally:
            update_id_context.reset(token)

    return wrapped


def _http_error_detail(exc: httpx.HTTPStatusError, fallback: str) -> str:
    try:
        payload = exc.response.json()
    except json.JSONDecodeError:
        logger.debug(
            "Bot API error response is not JSON status_code=%s",
            exc.response.status_code,
        )
        return fallback
    if not isinstance(payload, dict):
        logger.debug(
            "Bot API error JSON is not an object status_code=%s",
            exc.response.status_code,
        )
        return fallback
    detail = payload.get("detail")
    return str(detail) if detail else fallback


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


def _telegram_identity(update: Update) -> tuple[int, str | None]:
    user = update.effective_user
    if user is None:
        raise RuntimeError("Missing Telegram user")
    return user.id, user.username


def _allow_command(telegram_id: int) -> bool:
    return COMMAND_LIMITER.allow(str(telegram_id))


def _web_console_url() -> str:
    return dashboard_url(BotSettings().portal_public_url)


async def _send_panel_message(message, data: dict, *, telegram_id: int, include_photo: bool) -> None:
    settings = BotSettings()
    web_url = dashboard_url(settings.portal_public_url)
    panel_text = format_panel(data, telegram_id=telegram_id)
    panel_markup = build_panel_inline_keyboard(web_url)
    if include_photo and settings.telegram_welcome_image_url:
        try:
            await message.reply_photo(
                photo=settings.telegram_welcome_image_url,
                caption=panel_text,
                reply_markup=panel_markup,
            )
            return
        except Exception:
            logger.exception("Failed to send welcome image; falling back to text panel")
    await message.reply_text(panel_text, reply_markup=panel_markup)


async def _send_panel(update: Update, data: dict, *, include_photo: bool) -> None:
    telegram_id, _username = _telegram_identity(update)
    message = update.effective_message
    if message is None:
        return
    await _send_panel_message(message, data, telegram_id=telegram_id, include_photo=include_photo)


async def _replace_message_with_fresh_panel(update: Update, source_message) -> None:
    telegram_id, _username = _telegram_identity(update)
    fresh = await InternalApi().me(telegram_id)
    await _send_panel_message(source_message, fresh, telegram_id=telegram_id, include_photo=True)
    try:
        await source_message.delete()
    except Exception:
        logger.exception("Failed to delete old non-photo panel/prompt")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    api = InternalApi()
    try:
        data = await api.me(telegram_id)
    except Exception:
        logger.exception("Failed to load binding status")
        data = {"bound": False}
    await _send_panel(update, data, include_photo=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(format_help())


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, username = _telegram_identity(update)
    if not _allow_command(telegram_id):
        await update.effective_message.reply_text("操作过于频繁，请稍后再试。")
        return
    code = parse_bind_code(update.effective_message.text or "")
    if not code:
        await start_bind_flow(update, context)
        return
    await bind_code_value(update, context, code)


async def bind_code_value(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    telegram_id, username = _telegram_identity(update)
    api = InternalApi()
    try:
        data = await api.bind(code=code, telegram_id=telegram_id, telegram_username=username)
        context.user_data.pop(FLOW_KEY, None)
        await update.effective_message.reply_text(format_bind_success(data), reply_markup=build_panel_inline_keyboard(_web_console_url()))
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc, "绑定失败，请确认绑定码是否正确或已过期。")
        await update.effective_message.reply_text(f"绑定失败：{detail}", reply_markup=build_cancel_keyboard())


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    if not _allow_command(telegram_id):
        await update.effective_message.reply_text("操作过于频繁，请稍后再试。")
        return
    parsed = parse_register_args(update.effective_message.text or "")
    if parsed is None:
        await start_register_flow(update, context)
        return
    if not REGISTER_LIMITER.allow(str(telegram_id)):
        await update.effective_message.reply_text("开号请求过于频繁，请稍后再试。")
        return
    desired_username, invite_code = parsed
    await create_account(update, context, desired_username=desired_username, invite_code=invite_code)


async def start_register_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    if not REGISTER_LIMITER.allow(str(telegram_id)):
        await update.effective_message.reply_text("开号请求过于频繁，请稍后再试。")
        return
    context.user_data[FLOW_KEY] = {"step": FLOW_REGISTER_INVITE}
    await update.effective_message.reply_text(format_register_invite_prompt(), reply_markup=build_cancel_keyboard())


async def start_bind_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[FLOW_KEY] = {"step": FLOW_BIND_CODE}
    await update.effective_message.reply_text(format_bind_prompt(), reply_markup=build_cancel_keyboard())


async def handle_register_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    telegram_id, _username = _telegram_identity(update)
    try:
        info = await InternalApi().check_register_invite(invite_code=text, telegram_id=telegram_id)
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc, "邀请码不可用，请重新输入或取消。")
        await update.effective_message.reply_text(f"邀请码验证失败：{detail}", reply_markup=build_cancel_keyboard())
        return
    context.user_data[FLOW_KEY] = {"step": FLOW_REGISTER_USERNAME, "invite_code": text, "invite_info": info}
    await update.effective_message.reply_text(format_register_username_prompt(info), reply_markup=build_cancel_keyboard())


async def handle_register_username(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    telegram_id, _username = _telegram_identity(update)
    flow = context.user_data.get(FLOW_KEY) or {}
    invite_code = flow.get("invite_code")
    if not invite_code:
        await start_register_flow(update, context)
        return
    try:
        info = await InternalApi().check_register_username(username=text, invite_code=invite_code, telegram_id=telegram_id)
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc, "用户名不可用，请重新输入。")
        await update.effective_message.reply_text(f"用户名验证失败：{detail}", reply_markup=build_cancel_keyboard())
        return
    invite_info = flow.get("invite_info") or info
    context.user_data[FLOW_KEY] = {
        "step": FLOW_REGISTER_CONFIRM,
        "invite_code": invite_code,
        "invite_info": invite_info,
        "username": text,
    }
    await update.effective_message.reply_text(format_register_confirm_prompt(text, invite_info), reply_markup=build_register_confirm_keyboard())


async def create_account(update: Update, context: ContextTypes.DEFAULT_TYPE, *, desired_username: str, invite_code: str, message=None) -> None:
    telegram_id, username = _telegram_identity(update)
    message = message or update.effective_message
    api = InternalApi()
    try:
        data = await api.register(
            username=desired_username,
            invite_code=invite_code,
            telegram_id=telegram_id,
            telegram_username=username,
        )
        context.user_data.pop(FLOW_KEY, None)
        await message.reply_text(format_register_success(data), reply_markup=build_panel_inline_keyboard(_web_console_url()))
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc, "开号失败，请检查用户名和邀请码。")
        await message.reply_text(f"开号失败：{detail}", reply_markup=build_cancel_keyboard())


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    data = await InternalApi().me(telegram_id)
    await _send_panel(update, data, include_photo=False)


async def open_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    try:
        data = await InternalApi().open(telegram_id)
        await update.effective_message.reply_text(format_open(data), reply_markup=build_panel_inline_keyboard(_web_console_url()))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.effective_message.reply_text(format_me({"bound": False}))
            return
        await update.effective_message.reply_text("媒体账号状态暂时不可用，请稍后再试。")


async def library(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    data = await InternalApi().library_summary(telegram_id)
    await update.effective_message.reply_text(format_library_summary(data), reply_markup=build_panel_inline_keyboard(_web_console_url()))


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = _telegram_identity(update)
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("请发送：/search 关键词")
        return
    data = await InternalApi().search(telegram_id, query)
    await update.effective_message.reply_text(format_search_results(data), reply_markup=build_panel_inline_keyboard(_web_console_url()))


async def text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    flow = context.user_data.get(FLOW_KEY) or {}
    step = flow.get("step")
    if step == FLOW_REGISTER_INVITE:
        await handle_register_invite(update, context, text)
        return
    if step == FLOW_REGISTER_USERNAME:
        await handle_register_username(update, context, text)
        return
    if step == FLOW_BIND_CODE:
        code = text if text.upper().startswith("TG-") else parse_bind_code(f"/bind {text}")
        if not code:
            await update.effective_message.reply_text("请直接发送绑定码，例如 TG-ABCD-1234。", reply_markup=build_cancel_keyboard())
            return
        await bind_code_value(update, context, code)
        return
    if text in {"👤 用户面板", "用户面板"}:
        await me(update, context)
        return
    if text in {"📚 媒体库", "媒体库"}:
        await library(update, context)
        return
    if text in {"👑 创建账户", "🎟️ 使用注册码", "创建账户", "使用注册码"}:
        await start_register_flow(update, context)
        return
    if text in {"🔍 绑定TG", "绑定TG"}:
        await start_bind_flow(update, context)
        return
    if text in {"⭕ 换绑TG", "换绑TG"}:
        await update.effective_message.reply_text(
            "换绑需要先在网页控制台解绑当前 Telegram，再用新账号发送绑定码。",
            reply_markup=build_panel_inline_keyboard(_web_console_url()),
        )
        return
    if text in {"🌐 网页控制台", "网页控制台"}:
        await update.effective_message.reply_text(
            f"网页控制台：{_web_console_url()}",
            reply_markup=build_panel_inline_keyboard(_web_console_url()),
        )
        return
    if text in {"🎯 签到", "签到"}:
        await update.effective_message.reply_text("签到功能暂未开放。当前可使用开户注册、绑定、查库和账号面板。", reply_markup=build_panel_inline_keyboard(_web_console_url()))
        return
    await update.effective_message.reply_text(format_help(), reply_markup=build_panel_inline_keyboard(_web_console_url()))


async def callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    if data == "register_start":
        await start_register_flow(update, context)
    elif data == "bind_start":
        await start_bind_flow(update, context)
    elif data == "register_retry_username":
        flow = context.user_data.get(FLOW_KEY) or {}
        invite_info = flow.get("invite_info") or {}
        context.user_data[FLOW_KEY] = {**flow, "step": FLOW_REGISTER_USERNAME}
        if query.message is not None:
            await query.message.reply_text(format_register_username_prompt(invite_info), reply_markup=build_cancel_keyboard())
    elif data == "register_confirm":
        flow = context.user_data.get(FLOW_KEY) or {}
        if flow.get("step") != FLOW_REGISTER_CONFIRM or not flow.get("username") or not flow.get("invite_code"):
            if query.message is not None:
                await query.message.reply_text("注册流程已失效，请重新点击创建账户。")
            context.user_data.pop(FLOW_KEY, None)
            return
        if query.message is not None:
            await create_account(update, context, desired_username=flow["username"], invite_code=flow["invite_code"], message=query.message)
    elif data == "flow_cancel":
        context.user_data.pop(FLOW_KEY, None)
        if query.message is not None:
            await _replace_message_with_fresh_panel(update, query.message)
    elif data == "panel_refresh":
        if query.message is not None:
            telegram_id, _username = _telegram_identity(update)
            fresh = await InternalApi().me(telegram_id)
            text = format_panel(fresh, telegram_id=telegram_id)
            markup = build_panel_inline_keyboard(_web_console_url())
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=text, reply_markup=markup)
                else:
                    await _replace_message_with_fresh_panel(update, query.message)
            except Exception as exc:
                if "message is not modified" in str(exc).lower():
                    await query.answer("已是最新状态", show_alert=False)
                    return
                logger.exception("Failed to edit refreshed panel")
                await query.answer("刷新失败，请稍后再试。", show_alert=False)
    elif data == "library":
        if query.message is not None:
            telegram_id, _username = _telegram_identity(update)
            summary = await InternalApi().library_summary(telegram_id)
            await query.message.reply_text(format_library_summary(summary), reply_markup=build_panel_inline_keyboard(_web_console_url()))


async def setup_bot_commands(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("start", "打开图文用户面板"),
            BotCommand("register", "使用邀请码创建账户"),
            BotCommand("bind", "绑定已有 Web 账号"),
            BotCommand("me", "查看账号状态"),
            BotCommand("open", "查看媒体账号开通状态"),
            BotCommand("library", "查看媒体库"),
            BotCommand("search", "搜索作品"),
            BotCommand("help", "查看帮助"),
        ]
    )


def build_application(settings: BotSettings | None = None) -> Application:
    settings = settings or BotSettings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(settings.telegram_bot_token).post_init(setup_bot_commands).build()
    app.add_handler(CommandHandler("start", guarded_handler(start)))
    app.add_handler(CommandHandler("help", guarded_handler(help_command)))
    app.add_handler(CommandHandler("bind", guarded_handler(bind)))
    app.add_handler(CommandHandler("register", guarded_handler(register)))
    app.add_handler(CommandHandler("me", guarded_handler(me)))
    app.add_handler(CommandHandler("open", guarded_handler(open_account)))
    app.add_handler(CommandHandler("library", guarded_handler(library)))
    app.add_handler(CommandHandler("search", guarded_handler(search)))
    app.add_handler(CallbackQueryHandler(guarded_handler(callback_menu)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guarded_handler(text_menu)))
    app.add_error_handler(global_error_handler)
    return app


def main() -> None:
    app = build_application()
    logger.info("MoYin Telegram bot starting in polling mode")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
