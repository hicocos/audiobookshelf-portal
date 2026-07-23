from __future__ import annotations

import time
import secrets
from collections import defaultdict, deque
from datetime import UTC, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

STATUS_TEXT = {
    "active": "正常",
    "expired": "已到期",
    "disabled": "已停用",
    "deleted": "需处理",
}

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


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


def format_shanghai_datetime(value: Any, *, fallback: str = "未知") -> str:
    if value in (None, ""):
        return fallback
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            parsed = datetime.fromtimestamp(timestamp, tz=UTC)
        else:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(SHANGHAI_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return fallback


def dashboard_url(portal_public_url: str) -> str:
    return portal_public_url.rstrip("/") + "/dashboard"


def build_main_keyboard(web_console_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🏠 用户首页"), KeyboardButton("❓ 使用帮助")],
            [KeyboardButton("🌐 网页控制台", web_app=WebAppInfo(url=web_console_url))],
        ],
        resize_keyboard=True,
        input_field_placeholder="选择功能，或直接发送内容",
    )


def build_panel_inline_keyboard(
    web_console_url: str,
    data: dict[str, Any] | None = None,
    *,
    show_admin: bool = False,
) -> InlineKeyboardMarkup:
    data = data or {}
    features = data.get("features") if isinstance(data.get("features"), dict) else {}
    actions: list[InlineKeyboardButton] = []
    if not data.get("bound"):
        actions.extend(
            (
                InlineKeyboardButton("👑 创建账户", callback_data="register_start"),
                InlineKeyboardButton("🔗 绑定已有账号", callback_data="bind_start"),
                InlineKeyboardButton("❓ 使用帮助", callback_data="help_home"),
                InlineKeyboardButton("🔄 刷新状态", callback_data="panel_refresh"),
            )
        )
    else:
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        if user.get("status") in {"active", "expired"}:
            if (
                show_admin
                and user.get("status") == "active"
                and user.get("role") in {"admin", "root"}
                and features.get("adminEnabled", True)
            ):
                actions.append(
                    InlineKeyboardButton(
                        "🛡️ Bot 管理台", callback_data="admin_panel"
                    )
                )
            actions.append(
                InlineKeyboardButton("🌐 网页控制台", url=web_console_url)
            )
            actions.append(
                InlineKeyboardButton("👤 账号与安全", callback_data="menu_account")
            )
            if (
                user.get("status") == "active"
                and user.get("role") not in {"admin", "root"}
            ):
                if features.get("recentListeningEnabled", True):
                    actions.append(
                        InlineKeyboardButton("🎧 最近收听", callback_data="recent")
                    )
                actions.append(
                    InlineKeyboardButton("🔍 搜索有声书", callback_data="search_start")
                )
            if user.get("status") == "active" and any(
                features.get(key, default)
                for key, default in (
                    ("checkinEnabled", True),
                    ("pointsRedemptionEnabled", True),
                    ("referralEnabled", True),
                    ("requestsEnabled", True),
                    ("leaderboardEnabled", False),
                )
            ):
                actions.append(
                    InlineKeyboardButton(
                        "🎁 积分与社区", callback_data="menu_community"
                    )
                )
        actions.append(InlineKeyboardButton("❓ 使用帮助", callback_data="help_home"))
        if len(actions) % 2:
            actions.append(
                InlineKeyboardButton("🔄 刷新状态", callback_data="panel_refresh")
            )
    rows = [actions[index : index + 2] for index in range(0, len(actions), 2)]
    return InlineKeyboardMarkup(rows)


def build_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("‹ 返回首页", callback_data="panel_home")]]
    )


def build_help_keyboard(data: dict[str, Any] | None = None) -> InlineKeyboardMarkup:
    data = data or {}
    if not data.get("bound"):
        rows = [
            [
                InlineKeyboardButton("👑 创建账户", callback_data="register_start"),
                InlineKeyboardButton("🔗 绑定已有账号", callback_data="bind_start"),
            ]
        ]
    else:
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        rows = [[InlineKeyboardButton("👤 账号与安全", callback_data="menu_account")]]
        if user.get("status") == "active":
            rows.extend(
                [
                    [InlineKeyboardButton("🔍 搜索有声书", callback_data="search_start")],
                    [InlineKeyboardButton("🎁 积分与社区", callback_data="menu_community")],
                ]
            )
    rows.append([InlineKeyboardButton("‹ 返回首页", callback_data="panel_home")])
    return InlineKeyboardMarkup(rows)


def build_account_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    features = data.get("features") if isinstance(data.get("features"), dict) else {}
    rows: list[list[InlineKeyboardButton]] = []
    if features.get("renewalEnabled", True) and user.get("expiresAt") is not None:
        rows.append([InlineKeyboardButton("🎟️ 使用续期码", callback_data="renew_start")])
    if features.get("passwordResetEnabled", True):
        rows.append(
            [InlineKeyboardButton("🔑 重置登录密码", callback_data="reset_password")]
        )
    rows.append([InlineKeyboardButton("‹ 返回首页", callback_data="panel_home")])
    return InlineKeyboardMarkup(rows)


def build_community_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    if user.get("status") != "active":
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("‹ 返回首页", callback_data="panel_home")]]
        )
    features = data.get("features") if isinstance(data.get("features"), dict) else {}
    rows: list[list[InlineKeyboardButton]] = []
    reward_row: list[InlineKeyboardButton] = []
    if features.get("checkinEnabled", True):
        reward_row.append(InlineKeyboardButton("🎯 每日签到", callback_data="checkin"))
    if features.get("pointsRedemptionEnabled", True):
        reward_row.append(InlineKeyboardButton("💎 我的积分", callback_data="points"))
    if reward_row:
        rows.append(reward_row)
    community_row: list[InlineKeyboardButton] = []
    if features.get("referralEnabled", True):
        community_row.append(
            InlineKeyboardButton("🎁 邀请好友", callback_data="referral")
        )
    if features.get("requestsEnabled", True):
        community_row.append(
            InlineKeyboardButton("📮 求有声书", callback_data="request_start")
        )
    if community_row:
        rows.append(community_row)
    if features.get("requestsEnabled", True):
        rows.append([InlineKeyboardButton("🗂 我的工单", callback_data="my_requests")])
    if features.get("leaderboardEnabled", False):
        rows.append(
            [InlineKeyboardButton("🏆 匿名积分榜", callback_data="leaderboard")]
        )
    rows.append([InlineKeyboardButton("‹ 返回首页", callback_data="panel_home")])
    return InlineKeyboardMarkup(rows)


def build_bind_keyboard(web_console_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌐 打开网页控制台", url=web_console_url)],
            [InlineKeyboardButton("取消", callback_data="flow_cancel")],
        ]
    )


def build_redeem_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("用积分兑换有效期", callback_data="redeem_prompt")],
            [InlineKeyboardButton("‹ 返回积分与社区", callback_data="menu_community")],
        ]
    )


def build_redeem_confirm_keyboard(days: int) -> InlineKeyboardMarkup:
    operation_id = secrets.token_urlsafe(9)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"确认兑换 {days} 天",
                    callback_data=f"redeem_confirm:{days}:{operation_id}",
                )
            ],
            [InlineKeyboardButton("取消", callback_data="input_cancel")],
        ]
    )


def build_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("取消", callback_data="flow_cancel")]]
    )


def build_register_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认创建账户", callback_data="register_confirm")],
            [
                InlineKeyboardButton(
                    "重新开始", callback_data="register_retry_username"
                ),
                InlineKeyboardButton("取消", callback_data="flow_cancel"),
            ],
        ]
    )


def build_renew_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认续期", callback_data="renew_confirm")],
            [InlineKeyboardButton("取消", callback_data="flow_cancel")],
        ]
    )


def build_leaderboard_keyboard(opted_in: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "退出排行榜" if opted_in else "自愿加入排行榜",
                    callback_data="leaderboard_opt_out"
                    if opted_in
                    else "leaderboard_opt_in",
                )
            ]
        ]
    )


def format_register_invite_prompt() -> str:
    return "创建账户 · 第 1 步 / 3\n\n请直接发送邀请码。\n\n系统会先验证邀请码是否可用，不会立即消耗。"


def format_register_username_prompt(invite_info: dict[str, Any]) -> str:
    duration = invite_info.get("durationDays")
    duration_text = "永久" if duration == 0 else f"{duration} 天"
    designated = invite_info.get("designatedUsername")
    extra = f"\n该邀请码指定用户名：{designated}" if designated else ""
    return f"邀请码可用。\n有效期：{duration_text}{extra}\n\n创建账户 · 第 2 步 / 3\n请发送你想使用的用户名。\n\n允许：英文、数字、下划线、点、短横线，3-18 位。"


def format_register_confirm_prompt(username: str, invite_info: dict[str, Any]) -> str:
    duration = invite_info.get("durationDays")
    duration_text = "永久" if duration == 0 else f"{duration} 天"
    return f"创建账户 · 第 3 步 / 3\n\n用户名：{escape(username)}\n有效期：{duration_text}\n\n确认后会创建账号并绑定当前 Telegram。初始密码只显示一次。"


def format_bind_prompt() -> str:
    return "绑定已有 Web 账号：\n\n1. 打开网页控制台。\n2. 在账号中心生成 Telegram 绑定码。\n3. 直接把绑定码发给我，例如 TG-ABCD-1234。"


def format_request_notice() -> str:
    return (
        "目前仅提供喜马拉雅 FM 上的资源。\n\n"
        "请提供详细信息，否则不予处理，包括但不限于：\n"
        "平台：喜马拉雅 FM\n"
        "作品名称：\n"
        "演播者：\n"
        "是否完结：\n"
        "目前集数：\n\n"
        "请按以上格式填写并发送。"
    )


def format_expiry_remaining(seconds: float) -> str:
    if seconds <= 0:
        return "今天到期"
    if seconds < 86400:
        return "不足 1 天"
    days = int((seconds + 86399) // 86400)
    return f"约 {days} 天"


def format_panel(data: dict[str, Any], *, telegram_id: int) -> str:
    bound = bool(data.get("bound"))
    if not bound:
        return (
            "👋 欢迎来到 MoYin.CC\n\n"
            "你还没有关联账号，请选择一种开始方式：\n\n"
            "👑 有邀请码 · 创建新账号\n"
            "🔗 已有网页账号 · 绑定到 Telegram\n\n"
            "点按钮后按提示操作即可，不需要记命令。"
        )
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "你的账号"))
    raw_status = str(user.get("status") or "")
    status = STATUS_TEXT.get(raw_status, raw_status or "正常")
    status_icon = {"active": "🟢", "expired": "🟠", "disabled": "🔴"}.get(
        raw_status, "⚪"
    )
    expires_at = user.get("expiresAt")
    is_telegram_admin = bool(data.get("telegramAdmin"))
    expires_text = (
        "白名单"
        if is_telegram_admin
        else ("永久有效" if not expires_at else format_shanghai_datetime(expires_at))
    )
    remaining = ""
    if expires_at and not is_telegram_admin:
        try:
            expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires
            remaining = f"（{format_expiry_remaining((expires - datetime.now(UTC)).total_seconds())}）"
        except ValueError:
            remaining = ""
    hint = {
        "expired": "账号已到期，可进入“账号与安全”续期。",
        "disabled": "账号当前不可用，如有疑问请联系管理员。",
        "deleted": "账号需要管理员处理，请暂时不要重复操作。",
    }.get(raw_status, "今天想做什么？")
    panel = (
        f"👋 欢迎回来，{username}\n\n"
        f"{status_icon} 账号状态：{status}\n"
        f"⏳ 有效期：{expires_text}{remaining}\n\n"
        f"{hint}"
    )
    if "recentListening" in data:
        panel += "\n\n" + format_recent_listening(
            {"progress": data.get("recentListening") or []}
        )
    return panel


def format_help(data: dict[str, Any] | None = None) -> str:
    if not data or not data.get("bound"):
        return (
            "❓ 怎么开始\n\n"
            "第一次使用：点“创建账户”，依次发送邀请码和想要的用户名。\n\n"
            "已经有账号：点“绑定已有账号”，按提示生成并发送绑定码。\n\n"
            "操作中想退出，点“取消”或发送 /cancel。"
        )
    return (
        "❓ 使用帮助\n\n"
        "所有功能都可以点按钮完成，不需要记命令：\n\n"
        "👤 账号与安全 · 续期、重置密码\n"
        "🎧 最近收听 · 首页最多展示 2 条\n"
        "🔍 搜索有声书 · 搜索你有权限访问的馆藏\n"
        "🎁 积分与社区 · 签到、兑换、邀请、求有声书\n\n"
        "其他站点功能请前往网页控制台。\n\n"
        "随时发送 /start 返回首页；操作中发送 /cancel 可退出。"
    )


def format_renew_prompt() -> str:
    return "账号续期 · 第 1 步 / 2\n\n请直接发送续期码。系统会先展示续期结果，确认后才会消耗。"


def format_renew_preview(data: dict[str, Any]) -> str:
    duration = data.get("durationDays")
    duration_text = "永久" if data.get("permanent") else f"{duration} 天"
    current = format_shanghai_datetime(
        data.get("currentExpiresAt"), fallback="已到期"
    )
    target = format_shanghai_datetime(
        data.get("nextExpiresAt"), fallback="永久有效"
    )
    return (
        "账号续期 · 第 2 步 / 2\n\n"
        f"本次增加：{escape(str(duration_text))}\n"
        f"当前到期：{escape(str(current))}\n"
        f"续期后：{escape(str(target))}\n\n"
        "确认后将立即消耗续期码。"
    )


def format_renew_success(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    expiry = format_shanghai_datetime(user.get("expiresAt"), fallback="永久有效")
    return f"{escape(str(data.get('message') or '续期成功。'))}\n新有效期：{escape(str(expiry))}"


def format_reset_link(data: dict[str, Any]) -> str:
    return (
        "一次性密码重置链接（请勿转发）：\n"
        f"{escape(str(data.get('url') or ''))}\n\n"
        f"有效期至：{format_shanghai_datetime(data.get('expiresAt'))}\n"
        "使用一次后立即失效。"
    )


def format_checkin(data: dict[str, Any]) -> str:
    if data.get("alreadyCheckedIn"):
        return (
            f"今天已经签到过了。\n连续签到：{data.get('streak', 0)} 天\n"
            f"当前积分：{data.get('balance', 0)}"
        )
    return (
        f"签到成功，获得 {data.get('pointsAwarded', 0)} 积分。\n"
        f"连续签到：{data.get('streak', 0)} 天\n当前积分：{data.get('balance', 0)}"
    )


def format_points(data: dict[str, Any]) -> str:
    lines = [
        "💎 积分账户",
        f"当前余额：{data.get('balance', 0)}",
        f"累计获得：{data.get('lifetimeEarned', 0)}",
        f"连续签到：{data.get('streak', 0)} 天",
    ]
    if data.get("lastCheckinDate"):
        lines.append(f"最近签到：{data.get('lastCheckinDate')}")
    lines.append("\n如需兑换账号有效期，请点下方按钮。")
    return "\n".join(lines)


def format_points_redemption(data: dict[str, Any]) -> str:
    return (
        f"积分兑换成功：账号增加 {data.get('days')} 天。\n"
        f"消耗积分：{data.get('cost')}\n剩余积分：{data.get('balance')}\n"
        f"新有效期：{format_shanghai_datetime(data.get('expiresAt'))}"
    )


def format_referral(data: dict[str, Any]) -> str:
    state = "当前未使用的邀请" if data.get("existing") else "新的好友邀请"
    return (
        f"🎁 {state}\n\n邀请码：{data.get('code')}\n"
        f"有效期至：{format_shanghai_datetime(data.get('expiresAt'))}\n"
        f"好友账号有效期：{data.get('accountDays')} 天\n"
        f"好友成功注册后，你会获得 {data.get('rewardPoints')} 积分。\n\n"
        "邀请码仅可使用一次，请只发给你信任的人。"
    )


def format_leaderboard(data: dict[str, Any]) -> str:
    entries = data.get("entries") or []
    if not entries:
        return "排行榜暂时没有自愿参与的用户。"
    lines = ["🏆 匿名积分榜"]
    for item in entries:
        lines.append(
            f"{item.get('rank')}. {escape(str(item.get('displayName') or '***'))} · "
            f"{item.get('lifetimeEarned', 0)} 分"
        )
    lines.append("\n榜单只显示主动参与者和匿名用户名，不展示收听行为。")
    return "\n".join(lines)


def format_media_requests(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    if not items:
        return "你还没有提交有声书工单。"
    labels = {
        "pending": "待处理",
        "accepted": "已接受",
        "available": "已入库",
        "rejected": "已拒绝",
    }
    lines = ["📮 我的工单"]
    for item in items[:10]:
        lines.append(
            f"- [{labels.get(str(item.get('status')), item.get('status'))}] "
            f"{escape(str(item.get('title') or ''))}"
        )
    return "\n".join(lines)


def format_recent_listening(data: dict[str, Any]) -> str:
    items = (data.get("progress") or [])[:2]
    lines = ["🎧 最近收听"]
    if not items:
        lines.append("暂无收听记录。")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        title = escape(str(item.get("title") or "未命名作品"))
        progress = float(item.get("progressPercent") or 0)
        narrator = escape(str(item.get("narrator") or "").strip())
        detail = f"{progress:g}%"
        if narrator:
            detail += f" · {narrator}"
        updated = format_shanghai_datetime(item.get("lastUpdate"), fallback="")
        if updated:
            detail += f" · {updated}"
        lines.append(f"{index}. {title}\n   {detail}")
    return "\n".join(lines)


def format_search_results(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    query = escape(str(data.get("query") or ""))
    if not items:
        return f"没有找到与“{query}”相关的有声书。"
    lines = [f"🔍 “{query}”的搜索结果"]
    for index, item in enumerate(items[:8], start=1):
        title = escape(str(item.get("title") or "未命名作品"))
        author = escape(str(item.get("author") or "作者未知"))
        narrator = escape(str(item.get("narrator") or "").strip())
        duration = float(item.get("durationHours") or 0)
        metadata = f"{author} · 约 {duration:g} 小时"
        if narrator:
            metadata = f"{author} · {narrator} · 约 {duration:g} 小时"
        lines.append(f"{index}. {title}\n   {metadata}")
    return "\n".join(lines)


def format_bind_success(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "你的账号"))
    status = STATUS_TEXT.get(
        str(user.get("status") or ""), str(user.get("status") or "未知")
    )
    return f"✅ 绑定成功\n\n账号：{username}\n状态：{status}\n\n现在可以返回首页使用全部功能。"


def format_register_success(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    username = escape(str(user.get("username") or "你的账号"))
    password = escape(str(data.get("oneTimePassword") or ""))
    server_url = escape(str(data.get("serverUrl") or ""))
    expires_at = user.get("expiresAt")
    expires_text = (
        "永久有效" if not expires_at else format_shanghai_datetime(expires_at)
    )
    return (
        f"开号成功：{username}\n"
        f"初始密码：{password}\n"
        f"有效期：{expires_text}\n"
        f"服务地址：{server_url}\n\n"
        "重要：初始密码只显示一次，请立刻保存。登录 Web 账号中心后可以修改密码。"
    )
