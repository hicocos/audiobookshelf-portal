import logging
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from app.config import BotSettings
from app.handlers import (
    build_account_keyboard,
    build_bind_keyboard,
    build_cancel_keyboard,
    build_community_keyboard,
    build_help_keyboard,
    build_home_keyboard,
    build_leaderboard_keyboard,
    build_panel_inline_keyboard,
    build_redeem_confirm_keyboard,
    build_redeem_keyboard,
    build_register_confirm_keyboard,
    build_request_type_keyboard,
    build_renew_confirm_keyboard,
    dashboard_url,
    format_bind_prompt,
    format_bind_success,
    format_checkin,
    format_help,
    format_leaderboard,
    format_media_requests,
    format_panel,
    format_points,
    format_points_redemption,
    format_referral,
    format_recent_listening,
    format_request_notice,
    format_register_confirm_prompt,
    format_register_invite_prompt,
    format_register_success,
    format_register_username_prompt,
    format_renew_preview,
    format_renew_prompt,
    format_renew_success,
    format_reset_link,
    format_search_results,
    parse_bind_code,
)
from app.internal_api import InternalApi
from app.runtime import REGISTER_LIMITER, http_error_detail, telegram_identity

logger = logging.getLogger(__name__)
API = InternalApi()
INPUT_MODE_KEY = "input_mode"


def _web_url() -> str:
    return dashboard_url(BotSettings().portal_public_url)


def _is_allowlisted_admin(data: dict[str, Any], telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    settings = BotSettings()
    admin_ids = {
        item.strip() for item in settings.telegram_admin_ids.split(",") if item.strip()
    }
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return (
        str(telegram_id) in admin_ids
        and user.get("role") in {"admin", "root"}
        and user.get("status") == "active"
    )


def _panel_keyboard(
    data: dict[str, Any] | None = None,
    *,
    telegram_id: int | None = None,
):
    if data is None:
        return build_home_keyboard()
    show_admin = _is_allowlisted_admin(data, telegram_id)
    return build_panel_inline_keyboard(_web_url(), data, show_admin=show_admin)


async def _load_panel_data(telegram_id: int) -> dict[str, Any]:
    data = await API.me(telegram_id)
    data = dict(data)
    data["telegramAdmin"] = _is_allowlisted_admin(data, telegram_id)
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    features = data.get("features") if isinstance(data.get("features"), dict) else {}
    if (
        data.get("bound")
        and user.get("status") == "active"
        and user.get("role") not in {"admin", "root"}
        and features.get("recentListeningEnabled", True)
    ):
        data = dict(data)
        data["recentListening"] = []
        try:
            recent = await API.recent_listening(telegram_id, limit=2)
            data["recentListening"] = (recent.get("progress") or [])[:2]
        except httpx.HTTPError:
            logger.warning(
                "Could not load recent listening for Telegram home",
                exc_info=True,
            )
    return data


async def _begin_local_input(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    mode: str,
) -> None:
    await API.start_flow(telegram_id, kind="input", step=mode)
    context.user_data[INPUT_MODE_KEY] = mode


async def _send_panel_message(
    message: Any,
    data: dict[str, Any],
    *,
    telegram_id: int,
    include_photo: bool,
) -> None:
    settings = BotSettings()
    data = dict(data)
    data["telegramAdmin"] = _is_allowlisted_admin(data, telegram_id)
    panel_text = format_panel(data, telegram_id=telegram_id)
    panel_markup = _panel_keyboard(data, telegram_id=telegram_id)
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


async def _send_panel(
    update: Update, data: dict[str, Any], *, include_photo: bool
) -> None:
    telegram_id, _username = telegram_identity(update)
    if update.effective_message is not None:
        await _send_panel_message(
            update.effective_message,
            data,
            telegram_id=telegram_id,
            include_photo=include_photo,
        )


async def _replace_message_with_fresh_panel(
    update: Update, source_message: Any
) -> None:
    telegram_id, _username = telegram_identity(update)
    fresh = await _load_panel_data(telegram_id)
    await _send_panel_message(
        source_message,
        fresh,
        telegram_id=telegram_id,
        include_photo=True,
    )
    try:
        await source_message.delete()
    except Exception:
        logger.debug("Could not delete previous flow message", exc_info=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    context.user_data.pop(INPUT_MODE_KEY, None)
    payload = context.args[0] if getattr(context, "args", None) else ""
    if payload.startswith("bind_"):
        await bind_code_value(update, payload.removeprefix("bind_"))
        return
    try:
        await API.cancel_flow(telegram_id)
    except httpx.HTTPError:
        logger.debug("Could not cancel flow while opening home", exc_info=True)
    try:
        data = await _load_panel_data(telegram_id)
    except httpx.HTTPError:
        logger.exception("Failed to load binding status")
        await update.effective_message.reply_text(
            "账号服务暂时不可用，当前无法确认绑定和账号状态，请稍后重试。"
        )
        return
    await _send_panel(update, data, include_photo=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.me(telegram_id)
    except httpx.HTTPError:
        data = {"bound": False}
    await update.effective_message.reply_text(
        format_help(data),
        reply_markup=build_help_keyboard(data),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    context.user_data.pop(INPUT_MODE_KEY, None)
    try:
        await API.cancel_flow(telegram_id)
        data = await API.me(telegram_id)
    except httpx.HTTPError:
        data = {"bound": False}
    await update.effective_message.reply_text(
        "已退出当前操作。",
        reply_markup=_panel_keyboard(data, telegram_id=telegram_id),
    )


async def start_register_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    telegram_id, _username = telegram_identity(update)
    context.user_data.pop(INPUT_MODE_KEY, None)
    if not REGISTER_LIMITER.allow(str(telegram_id)):
        await update.effective_message.reply_text("开号请求过于频繁，请稍后再试。")
        return
    await API.start_flow(telegram_id, kind="register", step="register_invite")
    await update.effective_message.reply_text(
        format_register_invite_prompt(),
        reply_markup=build_cancel_keyboard(),
    )


async def start_bind_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    context.user_data.pop(INPUT_MODE_KEY, None)
    await API.start_flow(telegram_id, kind="bind", step="bind_code")
    await update.effective_message.reply_text(
        format_bind_prompt(), reply_markup=build_bind_keyboard(_web_url())
    )


async def start_renew_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    context.user_data.pop(INPUT_MODE_KEY, None)
    try:
        await API.start_flow(telegram_id, kind="renew", step="renew_code")
        await update.effective_message.reply_text(
            format_renew_prompt(),
            reply_markup=build_cancel_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            f"无法开始续期：{http_error_detail(exc, '请确认账号已绑定且续期功能已开启。')}",
            reply_markup=_panel_keyboard(),
        )


async def bind_code_value(update: Update, code: str) -> None:
    telegram_id, username = telegram_identity(update)
    try:
        data = await API.bind(
            code=code,
            telegram_id=telegram_id,
            telegram_username=username,
        )
        await update.effective_message.reply_text(
            format_bind_success(data),
            reply_markup=_panel_keyboard(data, telegram_id=telegram_id),
        )
    except httpx.HTTPStatusError as exc:
        detail = http_error_detail(exc, "绑定失败，请确认绑定码是否正确或已过期。")
        await update.effective_message.reply_text(
            f"绑定失败：{detail}",
            reply_markup=build_cancel_keyboard(),
        )


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = parse_bind_code(update.effective_message.text or "")
    if not code:
        await start_bind_flow(update, context)
        return
    await bind_code_value(update, code)


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # All registrations use the same persisted, preview-before-create flow.
    # Command arguments are intentionally not allowed to bypass confirmation.
    await start_register_flow(update, context)


async def handle_register_invite(update: Update, text: str) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        info = await API.check_register_invite(
            invite_code=text, telegram_id=telegram_id
        )
    except httpx.HTTPStatusError as exc:
        detail = http_error_detail(exc, "邀请码不可用，请重新输入或取消。")
        await update.effective_message.reply_text(
            f"邀请码验证失败：{detail}",
            reply_markup=build_cancel_keyboard(),
        )
        return
    await update.effective_message.reply_text(
        format_register_username_prompt(info),
        reply_markup=build_cancel_keyboard(),
    )


async def handle_register_username(update: Update, text: str) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        info = await API.check_register_username(username=text, telegram_id=telegram_id)
    except httpx.HTTPStatusError as exc:
        detail = http_error_detail(exc, "用户名不可用，请重新输入。")
        await update.effective_message.reply_text(
            f"用户名验证失败：{detail}",
            reply_markup=build_cancel_keyboard(),
        )
        return
    await update.effective_message.reply_text(
        format_register_confirm_prompt(text, info),
        reply_markup=build_register_confirm_keyboard(),
    )


async def handle_renew_code(update: Update, text: str) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        preview = await API.renew_preview(telegram_id, text)
    except httpx.HTTPStatusError as exc:
        detail = http_error_detail(exc, "续期码不可用，请重新输入或取消。")
        await update.effective_message.reply_text(
            f"续期码验证失败：{detail}",
            reply_markup=build_cancel_keyboard(),
        )
        return
    await update.effective_message.reply_text(
        format_renew_preview(preview),
        reply_markup=build_renew_confirm_keyboard(),
    )


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    await _send_panel(update, await API.me(telegram_id), include_photo=False)


async def renew(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_renew_flow(update, context)


async def reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.password_reset(telegram_id)
        await update.effective_message.reply_text(
            format_reset_link(data), reply_markup=_panel_keyboard()
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "暂时无法生成重置链接。"),
            reply_markup=_panel_keyboard(),
        )


async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.checkin(telegram_id)
        await update.effective_message.reply_text(
            format_checkin(data), reply_markup=_panel_keyboard()
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "签到暂时不可用。")
        )


async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.rewards(telegram_id)
        await update.effective_message.reply_text(
            format_points(data),
            reply_markup=build_redeem_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "积分信息暂时不可用。")
        )


async def redeem_points_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if len(context.args) != 1 or not context.args[0].isdigit():
        telegram_id, _username = telegram_identity(update)
        await _begin_local_input(context, telegram_id, "redeem_days")
        await update.effective_message.reply_text(
            "💎 兑换有效期\n\n请发送想兑换的天数。\n系统会先让你确认，不会立即扣除积分。",
            reply_markup=build_cancel_keyboard(),
        )
        return
    days = int(context.args[0])
    await update.effective_message.reply_text(
        f"确认使用积分兑换 {days} 天账号有效期吗？",
        reply_markup=build_redeem_confirm_keyboard(days),
    )


async def _redeem_points(update: Update, days: int, operation_id: str) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.redeem_points(telegram_id, days, operation_id)
        await update.effective_message.reply_text(
            format_points_redemption(data), reply_markup=build_home_keyboard()
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "积分兑换失败。"),
            reply_markup=build_home_keyboard(),
        )


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.referral_invite(telegram_id)
        await update.effective_message.reply_text(
            format_referral(data), reply_markup=_panel_keyboard()
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "暂时无法生成好友邀请。")
        )


async def leaderboard_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        board = await API.leaderboard()
        rewards = await API.rewards(telegram_id)
        await update.effective_message.reply_text(
            format_leaderboard(board),
            reply_markup=build_leaderboard_keyboard(
                bool(rewards.get("leaderboardOptIn"))
            ),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "排行榜暂时不可用。")
        )


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.recent_listening(telegram_id, limit=2)
        await update.effective_message.reply_text(
            format_recent_listening(data),
            reply_markup=build_home_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "最近收听暂时不可用。"),
            reply_markup=build_home_keyboard(),
        )


async def _search_value(update: Update, query: str) -> None:
    telegram_id, _username = telegram_identity(update)
    cleaned = query.strip()
    if not cleaned or len(cleaned) > 100:
        await update.effective_message.reply_text(
            "请输入 1–100 个字符的搜索关键词。",
            reply_markup=build_cancel_keyboard(),
        )
        return
    try:
        data = await API.search(telegram_id, cleaned, limit=8)
        await update.effective_message.reply_text(
            format_search_results(data),
            reply_markup=build_home_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "搜索暂时不可用。"),
            reply_markup=build_home_keyboard(),
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if query:
        await _search_value(update, query)
        return
    telegram_id, _username = telegram_identity(update)
    await _begin_local_input(context, telegram_id, "library_search")
    await update.effective_message.reply_text(
        "🔍 搜索有声书\n\n请发送书名、作者或演播者关键词。",
        reply_markup=build_cancel_keyboard(),
    )


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args).strip()
    if not raw or " " not in raw:
        await update.effective_message.reply_text(
            "📮 想提交哪一类内容？\n\n" + format_request_notice(),
            reply_markup=build_request_type_keyboard(),
        )
        return
    kind_value, body = raw.split(" ", 1)
    kinds = {"book": "book", "书": "book", "podcast": "podcast", "播客": "podcast"}
    kind = kinds.get(kind_value.casefold())
    if kind is None:
        await update.effective_message.reply_text("类型只能是 book 或 podcast。")
        return
    title, separator, details = body.partition("|")
    if not title.strip():
        await update.effective_message.reply_text("请填写作品标题。")
        return
    await _submit_media_request(
        update,
        kind=kind,
        title=title.strip(),
        details=details.strip() if separator else None,
    )


async def _submit_media_request(
    update: Update,
    *,
    kind: str,
    title: str,
    details: str | None,
) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.create_media_request(
            telegram_id, kind=kind, title=title, details=details
        )
        item = data.get("item") or {}
        await update.effective_message.reply_text(
            f"✅ 工单已提交\n\n{item.get('title')}\n状态：待处理",
            reply_markup=build_home_keyboard(),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "工单提交失败。"),
            reply_markup=build_home_keyboard(),
        )


async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.media_requests(telegram_id)
        await update.effective_message.reply_text(
            format_media_requests(data), reply_markup=_panel_keyboard()
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "工单列表暂时不可用。")
        )


async def text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    telegram_id, _username = telegram_identity(update)
    try:
        flow = await API.flow(telegram_id)
    except httpx.HTTPStatusError:
        flow = {"active": False}
    step = flow.get("step") if flow.get("active") else None
    if step == "register_invite":
        await handle_register_invite(update, text)
        return
    if step == "register_username":
        await handle_register_username(update, text)
        return
    if step == "bind_code":
        await bind_code_value(update, text)
        return
    if step == "renew_code":
        await handle_renew_code(update, text)
        return

    input_mode = (
        step
        if step in {"request_book", "request_podcast", "library_search", "redeem_days"}
        else context.user_data.get(INPUT_MODE_KEY)
    )
    if isinstance(input_mode, str) and input_mode.startswith("admin_request_reply:"):
        from app.admin_handlers import handle_admin_request_reply

        request_id = input_mode.partition(":")[2]
        await handle_admin_request_reply(update, context, request_id, text)
        return
    if input_mode in {"request_book", "request_podcast"}:
        context.user_data.pop(INPUT_MODE_KEY, None)
        await API.cancel_flow(telegram_id)
        title, separator, details = text.partition("\n")
        if not title.strip():
            await update.effective_message.reply_text(
                "标题不能为空，请重新选择内容类型。",
                reply_markup=build_request_type_keyboard(),
            )
            return
        await _submit_media_request(
            update,
            kind="book" if input_mode == "request_book" else "podcast",
            title=title.strip(),
            details=details.strip() if separator and details.strip() else None,
        )
        return
    if input_mode == "library_search":
        if not text or len(text) > 100:
            await update.effective_message.reply_text(
                "请输入 1–100 个字符的搜索关键词。",
                reply_markup=build_cancel_keyboard(),
            )
            return
        context.user_data.pop(INPUT_MODE_KEY, None)
        await API.cancel_flow(telegram_id)
        await _search_value(update, text)
        return
    if input_mode == "redeem_days":
        if not text.isdigit() or int(text) < 1 or int(text) > 365:
            await update.effective_message.reply_text(
                "请输入 1–365 之间的整数天数。",
                reply_markup=build_cancel_keyboard(),
            )
            return
        context.user_data.pop(INPUT_MODE_KEY, None)
        await API.cancel_flow(telegram_id)
        days = int(text)
        await update.effective_message.reply_text(
            f"确认使用积分兑换 {days} 天账号有效期吗？",
            reply_markup=build_redeem_confirm_keyboard(days),
        )
        return

    menu = {
        "🏠 用户首页": me,
        "用户首页": me,
        "❓ 使用帮助": help_command,
        "使用帮助": help_command,
        "👤 用户面板": me,
        "用户面板": me,
        "🎯 每日签到": checkin_command,
        "每日签到": checkin_command,
        "💎 我的积分": points_command,
        "我的积分": points_command,
        "🎧 最近收听": recent_command,
        "最近收听": recent_command,
        "🔍 搜索有声书": search_command,
        "搜索有声书": search_command,
        "📮 求书工单": requests_command,
        "求书工单": requests_command,
        "🎁 邀请好友": referral_command,
        "邀请好友": referral_command,
    }
    if text in menu:
        await menu[text](update, context)
    elif text in {"👑 创建账户", "🎟️ 使用注册码", "创建账户", "使用注册码"}:
        await start_register_flow(update, context)
    elif text in {"🔍 绑定TG", "🔍 绑定 TG", "🔗 绑定已有账号", "绑定TG"}:
        await start_bind_flow(update, context)
    else:
        try:
            data = await API.me(telegram_id)
        except httpx.HTTPError:
            data = {"bound": False}
        await update.effective_message.reply_text(
            "我还不确定你想做什么。请从下方选择，或发送 /help 查看说明。",
            reply_markup=build_help_keyboard(data),
        )


async def callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    action = query.data or ""
    telegram_id, username = telegram_identity(update)
    if action.startswith("adm_"):
        from app.admin_handlers import admin_callback

        await admin_callback(update, context)
        return
    if action == "register_start":
        await start_register_flow(update, context)
    elif action == "bind_start":
        await start_bind_flow(update, context)
    elif action == "renew_start":
        await start_renew_flow(update, context)
    elif action in {"panel_home", "input_cancel"}:
        context.user_data.pop(INPUT_MODE_KEY, None)
        try:
            await API.cancel_flow(telegram_id)
        except httpx.HTTPError:
            logger.debug("Could not cancel flow while returning home", exc_info=True)
        if query.message is not None:
            await _replace_message_with_fresh_panel(update, query.message)
    elif action == "help_home":
        fresh = await API.me(telegram_id)
        await query.message.reply_text(
            format_help(fresh),
            reply_markup=build_help_keyboard(fresh),
        )
    elif action in {"menu_account", "menu_community"}:
        fresh = await API.me(telegram_id)
        if not fresh.get("bound"):
            await query.message.reply_text(
                format_help(fresh),
                reply_markup=build_help_keyboard(fresh),
            )
        elif action == "menu_account":
            await query.message.reply_text(
                "👤 账号与安全\n\n请选择要处理的事项。",
                reply_markup=build_account_keyboard(fresh),
            )
        else:
            await query.message.reply_text(
                "🎁 积分与社区\n\n签到、积分、好友邀请和求书都在这里。",
                reply_markup=build_community_keyboard(fresh),
            )
    elif action == "request_start":
        await query.message.reply_text(
            "📮 想提交哪一类内容？\n\n" + format_request_notice(),
            reply_markup=build_request_type_keyboard(),
        )
    elif action in {"request_book", "request_podcast"}:
        await _begin_local_input(context, telegram_id, action)
        label = "有声书" if action == "request_book" else "播客"
        await query.message.reply_text(
            f"📮 提交{label}\n\n请发送标题。\n如需补充说明，可从第二行开始填写。",
            reply_markup=build_cancel_keyboard(),
        )
    elif action == "recent":
        await recent_command(update, context)
    elif action == "search_start":
        await search_command(update, context)
    elif action == "redeem_prompt":
        await _begin_local_input(context, telegram_id, "redeem_days")
        await query.message.reply_text(
            "💎 兑换有效期\n\n请发送想兑换的天数。\n系统会先让你确认，不会立即扣除积分。",
            reply_markup=build_cancel_keyboard(),
        )
    elif action.startswith("redeem_confirm:"):
        context.user_data.pop(INPUT_MODE_KEY, None)
        parts = action.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2]:
            if query.message is not None:
                await query.edit_message_reply_markup(reply_markup=None)
            await _redeem_points(update, int(parts[1]), parts[2])
    elif action == "register_retry_username":
        await API.cancel_flow(telegram_id)
        await API.start_flow(telegram_id, kind="register", step="register_invite")
        await query.message.reply_text(
            format_register_invite_prompt(),
            reply_markup=build_cancel_keyboard(),
        )
    elif action == "register_confirm":
        try:
            data = await API.confirm_register(
                telegram_id=telegram_id,
                telegram_username=username,
            )
            await query.message.reply_text(
                format_register_success(data),
                reply_markup=_panel_keyboard(data, telegram_id=telegram_id),
            )
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(
                f"开号失败：{http_error_detail(exc, '注册流程已过期，请重新开始。')}"
            )
    elif action == "renew_confirm":
        try:
            data = await API.renew_confirm(telegram_id)
            await query.message.reply_text(
                format_renew_success(data),
                reply_markup=_panel_keyboard(data, telegram_id=telegram_id),
            )
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(
                f"续期失败：{http_error_detail(exc, '续期流程已过期，请重新开始。')}"
            )
    elif action == "reset_password":
        await reset_password(update, context)
    elif action == "checkin":
        await checkin_command(update, context)
    elif action == "points":
        await points_command(update, context)
    elif action == "referral":
        await referral_command(update, context)
    elif action == "my_requests":
        await requests_command(update, context)
    elif action == "leaderboard":
        await leaderboard_command(update, context)
    elif action in {"leaderboard_opt_in", "leaderboard_opt_out"}:
        enabled = action == "leaderboard_opt_in"
        try:
            await API.leaderboard_opt_in(telegram_id, enabled)
            await query.message.reply_text("排行榜参与设置已更新。")
            await leaderboard_command(update, context)
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(http_error_detail(exc, "排行榜设置失败。"))
    elif action == "admin_panel":
        from app.admin_handlers import admin_panel

        await admin_panel(update, context)
    elif action == "flow_cancel":
        context.user_data.pop(INPUT_MODE_KEY, None)
        await API.cancel_flow(telegram_id)
        if query.message is not None:
            await _replace_message_with_fresh_panel(update, query.message)
    elif action == "panel_refresh" and query.message is not None:
        fresh = await _load_panel_data(telegram_id)
        text = format_panel(fresh, telegram_id=telegram_id)
        markup = _panel_keyboard(fresh, telegram_id=telegram_id)
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=markup)
            else:
                await query.edit_message_text(text=text, reply_markup=markup)
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                await query.answer("已是最新状态")
            else:
                raise
