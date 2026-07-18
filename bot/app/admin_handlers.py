from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.handlers import format_shanghai_datetime
from app.runtime import http_error_detail, telegram_identity
from app.user_handlers import API, INPUT_MODE_KEY


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📮 工单管理", callback_data="adm_requests"),
                InlineKeyboardButton("🔄 刷新统计", callback_data="adm_refresh"),
            ],
            [
                InlineKeyboardButton("⏰ 7天内到期", callback_data="adm_users:expiring"),
                InlineKeyboardButton("🟠 已到期", callback_data="adm_users:expired"),
            ],
            [
                InlineKeyboardButton("⛔ 已停用", callback_data="adm_users:disabled"),
            ],
        ]
    )


def _format_stats(data: dict[str, Any]) -> str:
    users = data.get("users") or {}
    worker = data.get("worker") or {}
    return (
        "🛡️ Telegram 管理台\n\n"
        f"正常用户：{users.get('active', 0)}\n"
        f"到期用户：{users.get('expired', 0)}\n"
        f"停用用户：{users.get('disabled', 0)}\n"
        f"待处理工单：{data.get('pendingRequests', 0)}\n"
        f"群组宽限中：{data.get('groupGrace', 0)}\n"
        f"待投递通知：{data.get('pendingNotifications', 0)}\n"
        f"Worker：{'正常' if worker.get('healthy') else '异常'}"
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.admin_stats(telegram_id)
        await update.effective_message.reply_text(_format_stats(data), reply_markup=_admin_keyboard())
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "你没有 Telegram 管理权限。")
        )


async def _search_exact(telegram_id: int, username: str) -> dict[str, Any] | None:
    data = await API.admin_search_users(telegram_id, username)
    users = data.get("users") or []
    return next(
        (item for item in users if str(item.get("username", "")).casefold() == username.casefold()),
        users[0] if len(users) == 1 else None,
    )


def _user_keyboard(user: dict[str, Any]) -> InlineKeyboardMarkup:
    user_id = str(user.get("id"))
    rows: list[list[InlineKeyboardButton]] = []
    if user.get("expiresAt") is not None:
        rows.append(
            [
                InlineKeyboardButton("⏳ +7天", callback_data=f"adm_extend:7:{user_id}"),
                InlineKeyboardButton("⏳ +30天", callback_data=f"adm_extend:30:{user_id}"),
            ]
        )
    if user.get("status") == "active":
        rows.append(
            [InlineKeyboardButton("⛔ 停用", callback_data=f"adm_user:disable:{user_id}")]
        )
    elif user.get("status") == "disabled":
        rows.append(
            [InlineKeyboardButton("✅ 启用", callback_data=f"adm_user:enable:{user_id}")]
        )
    return InlineKeyboardMarkup(rows)


def _format_user(user: dict[str, Any]) -> str:
    expiry = format_shanghai_datetime(user.get("expiresAt"), fallback="永久")
    return (
        f"用户：{user.get('username')}\n状态：{user.get('status')}\n"
        f"有效期：{expiry}\nTG：{user.get('telegramId') or '未绑定'}"
    )


async def admin_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("请发送：/admin_user 用户名")
        return
    try:
        data = await API.admin_search_users(telegram_id, query)
        users = data.get("users") or []
        if not users:
            await update.effective_message.reply_text("没有找到用户。")
            return
        for user in users[:5]:
            await update.effective_message.reply_text(
                _format_user(user), reply_markup=_user_keyboard(user)
            )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(http_error_detail(exc, "用户查询失败。"))


async def admin_user_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category: str,
) -> None:
    telegram_id, _username = telegram_identity(update)
    labels = {
        "active": "正常账号",
        "expiring": "7 天内到期",
        "expired": "已到期账号",
        "disabled": "已停用账号",
    }
    try:
        data = await API.admin_list_users(telegram_id, category, limit=10)
        users = data.get("users") or []
        if not users:
            await update.effective_message.reply_text(
                f"当前没有{labels.get(category, '符合条件的账号')}。"
            )
            return
        await update.effective_message.reply_text(
            f"{labels.get(category, '账号列表')}（最多显示 10 个）"
        )
        for user in users:
            await update.effective_message.reply_text(
                _format_user(user),
                reply_markup=_user_keyboard(user),
            )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "账号列表加载失败。")
        )


async def _preview_named_action(
    update: Update,
    *,
    action: str,
    username: str,
    extend_days: int | None = None,
) -> None:
    telegram_id, _tg_username = telegram_identity(update)
    try:
        target = await _search_exact(telegram_id, username)
        if target is None:
            await update.effective_message.reply_text("没有找到唯一匹配的用户。")
            return
        await API.admin_action_preview(
            telegram_id,
            action=action,
            target_user_id=str(target.get("id")),
            extend_days=extend_days,
        )
        action_text = {"enable": "启用", "disable": "停用", "extend": f"延长 {extend_days} 天"}[action]
        await update.effective_message.reply_text(
            f"请确认管理员操作：\n用户：{target.get('username')}\n操作：{action_text}",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("确认执行", callback_data="adm_confirm"),
                    InlineKeyboardButton("取消", callback_data="flow_cancel"),
                ]]
            ),
        )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(http_error_detail(exc, "管理员操作预览失败。"))


async def admin_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = " ".join(context.args).strip()
    if not username:
        await update.effective_message.reply_text("请发送：/admin_disable 用户名")
        return
    await _preview_named_action(update, action="disable", username=username)


async def admin_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = " ".join(context.args).strip()
    if not username:
        await update.effective_message.reply_text("请发送：/admin_enable 用户名")
        return
    await _preview_named_action(update, action="enable", username=username)


async def admin_extend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2 or not context.args[1].isdigit():
        await update.effective_message.reply_text("请发送：/admin_extend 用户名 天数")
        return
    await _preview_named_action(
        update,
        action="extend",
        username=context.args[0],
        extend_days=int(context.args[1]),
    )


async def admin_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id, _username = telegram_identity(update)
    try:
        data = await API.admin_requests(telegram_id)
        items = data.get("items") or []
        if not items:
            await update.effective_message.reply_text("当前没有待处理工单。")
            return
        for item in items[:10]:
            request_id = str(item.get("id"))
            await update.effective_message.reply_text(
                f"{item.get('username')} · {item.get('title')}\n状态：{item.get('status')}\n"
                f"说明：{item.get('details') or '-'}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("接受", callback_data=f"adm_req:accepted:{request_id}"),
                            InlineKeyboardButton("已入库", callback_data=f"adm_req:available:{request_id}"),
                        ],
                        [
                            InlineKeyboardButton("💬 回复用户", callback_data=f"adm_req_reply:{request_id}"),
                            InlineKeyboardButton("拒绝", callback_data=f"adm_req:rejected:{request_id}"),
                        ],
                    ]
                ),
            )
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(http_error_detail(exc, "工单列表加载失败。"))


async def handle_admin_request_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    request_id: str,
    text: str,
) -> None:
    if not text or len(text) > 500:
        await update.effective_message.reply_text(
            "回复内容需为 1–500 个字符。发送 /cancel 可取消。"
        )
        return
    telegram_id, _username = telegram_identity(update)
    try:
        await API.admin_reply_request(telegram_id, request_id, text)
        context.user_data.pop(INPUT_MODE_KEY, None)
        await update.effective_message.reply_text("回复已发送给用户。")
    except httpx.HTTPStatusError as exc:
        await update.effective_message.reply_text(
            http_error_detail(exc, "回复发送失败，请重试或发送 /cancel 取消。")
        )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    action = query.data or ""
    telegram_id, _username = telegram_identity(update)
    if action in {"adm_refresh", "admin_panel"}:
        await admin_panel(update, context)
    elif action.startswith("adm_users:"):
        category = action.partition(":")[2]
        if category in {"active", "expiring", "expired", "disabled"}:
            await admin_user_list(update, context, category)
    elif action == "adm_requests":
        await admin_requests(update, context)
    elif action.startswith("adm_extend:"):
        _prefix, days_text, user_id = action.split(":", 2)
        if not days_text.isdigit():
            return
        days = int(days_text)
        try:
            preview = await API.admin_action_preview(
                telegram_id,
                action="extend",
                target_user_id=user_id,
                extend_days=days,
            )
            target = preview.get("target") or {}
            await query.message.reply_text(
                f"确认给用户 {target.get('username')} 延长 {days} 天？",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton("确认执行", callback_data="adm_confirm"),
                        InlineKeyboardButton("取消", callback_data="flow_cancel"),
                    ]]
                ),
            )
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(http_error_detail(exc, "续期预览失败。"))
    elif action.startswith("adm_user:"):
        _prefix, user_action, user_id = action.split(":", 2)
        try:
            preview = await API.admin_action_preview(
                telegram_id,
                action=user_action,
                target_user_id=user_id,
            )
            target = preview.get("target") or {}
            await query.message.reply_text(
                f"确认{ '启用' if user_action == 'enable' else '停用' }用户 {target.get('username')}？",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton("确认执行", callback_data="adm_confirm"),
                        InlineKeyboardButton("取消", callback_data="flow_cancel"),
                    ]]
                ),
            )
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(http_error_detail(exc, "操作预览失败。"))
    elif action == "adm_confirm":
        try:
            data = await API.admin_action_confirm(telegram_id)
            await query.message.reply_text(f"操作已完成。\n{_format_user(data.get('user') or {})}")
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(http_error_detail(exc, "确认操作失败。"))
    elif action.startswith("adm_req:"):
        _prefix, status, request_id = action.split(":", 2)
        try:
            await API.admin_update_request(telegram_id, request_id, status=status)
            await query.message.reply_text("工单状态已更新。")
        except httpx.HTTPStatusError as exc:
            await query.message.reply_text(http_error_detail(exc, "工单更新失败。"))
    elif action.startswith("adm_req_reply:"):
        request_id = action.partition(":")[2]
        context.user_data[INPUT_MODE_KEY] = f"admin_request_reply:{request_id}"
        await query.message.reply_text(
            "请直接发送要回复给用户的内容（1–500 字）。\n发送 /cancel 可取消。"
        )
