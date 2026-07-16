from __future__ import annotations

import time
from collections import defaultdict, deque
from html import escape
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

STATUS_TEXT = {
    "active": "正常",
    "expired": "已到期",
    "disabled": "已停用",
    "deleted": "需处理",
}


class SimpleRateLimiter:
    def __init__(self, *, max_calls: int, window_seconds: int) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        hits = self._hits[key]
        cutoff = current - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.max_calls:
            return False
        hits.append(current)
        return True


def parse_bind_code(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return None
    return parts[1].strip()


def parse_register_args(text: str) -> tuple[str, str] | None:
    parts = text.strip().split()
    if len(parts) != 3:
        return None
    return parts[1].strip(), parts[2].strip()


def dashboard_url(portal_public_url: str) -> str:
    return portal_public_url.rstrip("/") + "/dashboard"


def build_main_keyboard(web_console_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎟️ 使用注册码"), KeyboardButton("👑 创建账户")],
            [KeyboardButton("⭕ 换绑TG"), KeyboardButton("🔍 绑定TG")],
            [KeyboardButton("👤 用户面板"), KeyboardButton("📚 媒体库")],
            [KeyboardButton("🌐 网页控制台", web_app=WebAppInfo(url=web_console_url)), KeyboardButton("🎯 签到")],
        ],
        resize_keyboard=True,
        input_field_placeholder="选择菜单或输入 /help",
    )


def build_panel_inline_keyboard(web_console_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌐 网页控制台", url=web_console_url)],
            [
                InlineKeyboardButton("👑 创建账户", callback_data="register_start"),
                InlineKeyboardButton("🔍 绑定TG", callback_data="bind_start"),
            ],
            [InlineKeyboardButton("📚 媒体库", callback_data="library")],
            [InlineKeyboardButton("🔄 刷新面板", callback_data="panel_refresh")],
        ]
    )


def build_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data="flow_cancel")]])


def build_register_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认创建账户", callback_data="register_confirm")],
            [InlineKeyboardButton("重新输入用户名", callback_data="register_retry_username"), InlineKeyboardButton("取消", callback_data="flow_cancel")],
        ]
    )


def format_register_invite_prompt() -> str:
    return "创建账户 · 第 1 步 / 3\n\n请直接发送邀请码。\n\n系统会先验证邀请码是否可用，不会立即消耗。"


def format_register_username_prompt(invite_info: dict[str, Any]) -> str:
    duration = invite_info.get("durationDays")
    duration_text = "永久" if duration == 0 else f"{duration} 天"
    designated = invite_info.get("designatedUsername")
    extra = f"\n该邀请码指定用户名：{designated}" if designated else ""
    return f"邀请码可用。\n有效期：{duration_text}{extra}\n\n创建账户 · 第 2 步 / 3\n请发送你想使用的用户名。\n\n允许：英文、数字、下划线、点、短横线，3-64 位。"


def format_register_confirm_prompt(username: str, invite_info: dict[str, Any]) -> str:
    duration = invite_info.get("durationDays")
    duration_text = "永久" if duration == 0 else f"{duration} 天"
    return f"创建账户 · 第 3 步 / 3\n\n用户名：{escape(username)}\n有效期：{duration_text}\n\n确认后会创建账号并绑定当前 Telegram。初始密码只显示一次。"


def format_bind_prompt() -> str:
    return "绑定已有 Web 账号：\n\n1. 打开网页控制台。\n2. 在账号中心生成 Telegram 绑定码。\n3. 直接把绑定码发给我，例如 TG-ABCD-1234。"


def format_panel(data: dict[str, Any], *, telegram_id: int) -> str:
    bound = bool(data.get("bound"))
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "-"))
    status = STATUS_TEXT.get(str(user.get("status") or ""), str(user.get("status") or ("已注册" if bound else "未注册")))
    expires_at = user.get("expiresAt")
    expires_text = "永久有效" if bound and not expires_at else (str(expires_at).replace("T", " ").split("+")[0] if expires_at else "-")
    server_url = escape(str(data.get("serverUrl") or "-"))
    return (
        "欢迎进入 MoYin.CC 用户面板！ -z\n\n"
        f"🆔 用户ID | {telegram_id}\n"
        f"📊 当前状态 | {'已注册' if bound else '未注册'}\n"
        f"👤 账号 | {username}\n"
        f"Ⓡ 注册状态 | {str(bound)}\n"
        f"🛡️ 账号状态 | {status}\n"
        f"⏳ 有效期 | {expires_text}\n"
        f"🌐 网页控制台 | {server_url}\n\n"
        "你可以使用下方菜单完成开户注册、绑定、查库和打开网页控制台。"
    )


def format_help() -> str:
    return (
        "MoYin.CC Bot 命令：\n\n"
        "/bind <绑定码> - 绑定已有 Web 账号\n"
        "/register <用户名> <邀请码> - 直接开通新账号并绑定当前 Telegram\n"
        "/me - 查看账号状态\n"
        "/open - 查看媒体账号开通状态\n"
        "/library - 查看媒体库\n"
        "/search <关键词> - 搜索作品\n"
        "/help - 查看帮助\n\n"
        "绑定码请先登录 Web 账号中心生成。"
    )


def format_start(bound_data: dict[str, Any] | None = None) -> str:
    if bound_data and bound_data.get("bound"):
        return "欢迎回来。\n\n" + format_me(bound_data)
    return (
        "欢迎使用 MoYin.CC Bot。\n\n"
        "你还没有绑定 Web 账号。\n"
        "你可以选择：\n"
        "1. 登录 Web 账号中心生成绑定码，然后发送 /bind TG-ABCD-1234\n"
        "2. 如果你有邀请码，直接发送 /register 用户名 邀请码 开通新账号"
    )


def format_bind_success(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "你的账号"))
    status = STATUS_TEXT.get(str(user.get("status") or ""), str(user.get("status") or "未知"))
    return f"绑定成功：{username}\n状态：{status}\n\n之后可用 /me 查看账号，/library 查看媒体库。"


def format_register_success(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "你的账号"))
    password = escape(str(data.get("oneTimePassword") or ""))
    server_url = escape(str(data.get("serverUrl") or ""))
    expires_at = user.get("expiresAt")
    expires_text = "永久有效" if not expires_at else str(expires_at).replace("T", " ").split("+")[0]
    return (
        f"开号成功：{username}\n"
        f"初始密码：{password}\n"
        f"有效期：{expires_text}\n"
        f"服务地址：{server_url}\n\n"
        "重要：初始密码只显示一次，请立刻保存。登录 Web 账号中心后可以修改密码。"
    )


def format_me(data: dict[str, Any]) -> str:
    if not data.get("bound"):
        return "你还没有绑定 Web 账号。请先在 Web 账号中心生成绑定码，然后发送 /bind <绑定码>。"
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "未知"))
    status = STATUS_TEXT.get(str(user.get("status") or ""), str(user.get("status") or "未知"))
    expires_at = user.get("expiresAt")
    expires_text = "永久有效" if not expires_at else str(expires_at).replace("T", " ").split("+")[0]
    abs_username = escape(str(user.get("absUsername") or username))
    server_url = escape(str(data.get("serverUrl") or ""))
    return (
        f"账号：{username}\n"
        f"状态：{status}\n"
        f"有效期：{expires_text}\n"
        f"媒体账号：{abs_username}\n"
        f"服务地址：{server_url}"
    )


def format_open(data: dict[str, Any]) -> str:
    if data.get("opened"):
        user = data.get("user") or {}
        server_url = escape(str(data.get("serverUrl") or ""))
        return (
            "你的媒体账号已开通。\n"
            f"用户名：{escape(str(user.get('absUsername') or user.get('username') or '未知'))}\n"
            f"服务地址：{server_url}\n\n"
            "如果忘记密码，请到 Web 账号中心修改密码，会同步到听书 App。"
        )
    return "媒体账号暂未开通，请联系管理员。"


def format_library_summary(data: dict[str, Any]) -> str:
    if not data.get("bound"):
        return format_me(data)
    libraries = data.get("libraries") or []
    if not libraries:
        return "当前没有可见媒体库。"
    lines = [f"媒体库（{len(libraries)} 个）："]
    for item in libraries[:10]:
        lines.append(f"- {escape(str(item.get('name') or '未命名'))}（{escape(str(item.get('mediaType') or 'book'))}）")
    return "\n".join(lines)


def format_search_results(data: dict[str, Any]) -> str:
    if not data.get("bound"):
        return format_me(data)
    items = data.get("items") or []
    query = escape(str(data.get("query") or ""))
    if not items:
        return f"没有找到与“{query}”相关的作品。"
    lines = [f"搜索“{query}”找到 {len(items)} 个结果："]
    for index, item in enumerate(items[:8], start=1):
        title = escape(str(item.get("title") or "未命名作品"))
        author = escape(str(item.get("author") or "作者未知"))
        narrator = escape(str(item.get("narrator") or ""))
        duration = item.get("durationHours") or 0
        extra = f" · {narrator}" if narrator else ""
        lines.append(f"{index}. {title}\n   {author}{extra} · 约 {duration} 小时")
    return "\n".join(lines)
