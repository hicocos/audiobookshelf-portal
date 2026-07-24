import time
from collections.abc import Awaitable, Callable

import httpx
from telegram.error import TimedOut
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.config import BotSettings
from app.internal_api import InternalApi

BotHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
_config_cache: tuple[InternalApi, float, dict] | None = None
_membership_cache: dict[tuple[str, int], tuple[float, bool]] = {}
_MEMBERSHIP_CACHE_SECONDS = 60


def _admin_ids() -> set[str]:
    return {
        item.strip()
        for item in BotSettings().telegram_admin_ids.split(",")
        if item.strip()
    }


async def _config(api: InternalApi) -> dict:
    global _config_cache
    now = time.monotonic()
    if _config_cache and _config_cache[0] is api and now - _config_cache[1] < 60:
        return _config_cache[2]
    value = await api.community_config()
    _config_cache = (api, now, value)
    return value


def _is_member(member) -> bool:
    if member.status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }:
        return True
    return member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))


def required_group_handler(handler: BotHandler, api: InternalApi) -> BotHandler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or str(user.id) in _admin_ids():
            await handler(update, context)
            return
        callback_data = str(getattr(update.callback_query, "data", "") or "")
        message_text = str(getattr(update.effective_message, "text", "") or "").strip().upper()
        if callback_data == "bind_start" or message_text.startswith("TG-"):
            await handler(update, context)
            return
        try:
            config = await _config(api)
        except httpx.HTTPError:
            await update.effective_message.reply_text("群组资格暂时无法验证，请稍后重试。")
            return
        group_id = str(config.get("groupId") or "")
        if not config.get("enabled") or not group_id:
            await handler(update, context)
            return
        if config.get("scope") == "new_users_only":
            try:
                eligibility = await api.community_eligibility(user.id)
            except httpx.HTTPError:
                await update.effective_message.reply_text("群组资格范围暂时无法确认，请稍后重试。")
                return
            if not eligibility.get("applicable"):
                await handler(update, context)
                return
        try:
            cache_key = (group_id, user.id)
            cached = _membership_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < _MEMBERSHIP_CACHE_SECONDS:
                is_member = cached[1]
            else:
                member = await context.bot.get_chat_member(chat_id=group_id, user_id=user.id)
                is_member = _is_member(member)
                _membership_cache[cache_key] = (time.monotonic(), is_member)
        except TelegramError:
            await update.effective_message.reply_text("群组资格暂时无法验证，请联系管理员检查 Bot 权限。")
            return
        membership = await api.report_membership(user.id, group_id=group_id, is_member=is_member)
        if is_member:
            await handler(update, context)
            return
        invite_url = str(config.get("inviteUrl") or "")
        markup = (
            InlineKeyboardMarkup([[InlineKeyboardButton("加入必需群组", url=invite_url)]])
            if invite_url
            else None
        )
        query = update.callback_query
        if query is not None:
            try:
                await query.answer()
            except TimedOut:
                pass
        grace_deadline = str(membership.get("graceExpiresAt") or "").strip()
        if membership.get("status") == "grace" and grace_deadline:
            text = (
                "你当前不在必需群组，因此 Bot 功能已暂停。"
                f"媒体账号宽限期至 {grace_deadline}；加入群组后请重新发送命令。"
            )
        else:
            text = "使用 Bot 前需要先加入指定群组。加入后请重新发送命令。"
        await update.effective_message.reply_text(
            text,
            reply_markup=markup,
        )

    return wrapped


async def chat_member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    api: InternalApi,
) -> None:
    change = update.chat_member
    if change is None:
        return
    try:
        config = await _config(api)
    except httpx.HTTPError:
        return
    group_id = str(config.get("groupId") or "")
    if not config.get("enabled") or str(change.chat.id) != group_id:
        return
    member_user = change.new_chat_member.user
    if member_user.is_bot:
        return
    is_member = _is_member(change.new_chat_member)
    _membership_cache[(group_id, member_user.id)] = (time.monotonic(), is_member)
    await api.report_membership(
        member_user.id,
        group_id=group_id,
        is_member=is_member,
    )
