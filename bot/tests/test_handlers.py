import pytest
from telegram import BotCommand

from app.handlers import (
    SimpleRateLimiter,
    build_account_keyboard,
    build_bind_keyboard,
    build_community_keyboard,
    build_help_keyboard,
    build_main_keyboard,
    build_panel_inline_keyboard,
    build_request_type_keyboard,
    format_bind_success,
    format_help,
    format_panel,
    format_recent_listening,
    format_request_notice,
    format_register_success,
    format_search_results,
    format_shanghai_datetime,
    format_expiry_remaining,
    parse_bind_code,
    parse_register_args,
)
from app.admin_handlers import _admin_keyboard, _user_keyboard
from app.user_handlers import _load_panel_data, _panel_keyboard, start
from app.main import build_command_menu


def test_parse_bind_code_requires_code():
    assert parse_bind_code("/bind") is None
    assert parse_bind_code("/bind TG-ABCD-1234") == "TG-ABCD-1234"


def test_format_bind_success_points_back_to_home_instead_of_commands():
    text = format_bind_success({"user": {"username": "alice", "status": "active"}})
    assert "绑定成功" in text
    assert "alice" in text
    assert "返回首页" in text
    assert "/me" not in text


def test_format_help_guides_users_progressively_instead_of_listing_commands():
    unbound = format_help({"bound": False})
    assert "创建账户" in unbound
    assert "绑定已有账号" in unbound
    assert "/bind" not in unbound

    bound = format_help({"bound": True})
    assert "账号与安全" in bound
    assert "积分与社区" in bound
    assert "搜索有声书" in bound
    assert "网页控制台" in bound
    assert "找书与收听" not in bound
    assert "/redeem_points" not in bound


def test_parse_register_args_requires_username_and_invite_code():
    assert parse_register_args("/register") is None
    assert parse_register_args("/register alice INVITE-123") == ("alice", "INVITE-123")


def test_format_register_success_returns_one_time_password_warning():
    text = format_register_success(
        {
            "user": {"username": "alice", "expiresAt": None},
            "oneTimePassword": "secret-pass",
            "serverUrl": "https://moyin.cc",
        }
    )
    assert "开号成功" in text
    assert "alice" in text
    assert "secret-pass" in text
    assert "只显示一次" in text


def test_simple_rate_limiter_limits_repeated_calls():
    limiter = SimpleRateLimiter(max_calls=2, window_seconds=60)
    assert limiter.allow("u1", now=1000) is True
    assert limiter.allow("u1", now=1001) is True
    assert limiter.allow("u1", now=1002) is False
    assert limiter.allow("u1", now=1061) is True


def test_format_panel_contains_public_account_status():
    text = format_panel({"bound": False}, telegram_id=7974849843)
    assert "欢迎来到" in text
    assert "创建新账号" in text
    assert "绑定到 Telegram" in text
    assert "7974849843" not in text

    bound = format_panel(
        {
            "bound": True,
            "serverUrl": "https://listen.moyin.cc",
            "user": {"username": "alice", "status": "active", "expiresAt": None},
        },
        telegram_id=1,
    )
    assert "alice" in bound
    assert "账号状态：正常" in bound
    assert "永久有效" in bound
    assert "https://listen.moyin.cc" not in bound


def test_bot_dates_are_always_rendered_in_shanghai_timezone():
    assert format_shanghai_datetime("2026-07-17T00:00:00Z") == "2026-07-17 08:00"
    text = format_panel(
        {
            "bound": True,
            "user": {
                "username": "alice",
                "status": "active",
                "expiresAt": "2026-07-17T00:00:00Z",
            },
        },
        telegram_id=1,
    )
    assert "2026-07-17 08:00" in text
    assert "上海时间" not in text


def test_expiry_remaining_does_not_show_zero_days_for_future_expiry():
    assert format_expiry_remaining(23 * 3600) == "不足 1 天"
    assert format_expiry_remaining(0) == "今天到期"
    assert format_expiry_remaining(2 * 86400 + 60) == "约 3 天"


def test_build_main_keyboard_keeps_only_stable_navigation():
    markup = build_main_keyboard("https://moyin.cc/dashboard")
    labels = [
        button.text if hasattr(button, "text") else str(button)
        for row in markup.keyboard
        for button in row
    ]
    assert "🏠 用户首页" in labels
    assert "❓ 使用帮助" in labels
    assert "🌐 网页控制台" in labels
    assert "🎟️ 使用注册码" not in labels


def test_command_menu_exposes_supported_account_capabilities():
    commands = build_command_menu()
    assert all(isinstance(item, BotCommand) for item in commands)
    names = {item.command for item in commands}
    assert {"me", "renew", "reset_password", "checkin", "points", "referral", "requests"} <= names


@pytest.mark.asyncio
async def test_start_deep_link_binds_generated_code(monkeypatch):
    called = {}

    async def fake_bind(update, code):
        called["code"] = code

    monkeypatch.setattr("app.user_handlers.bind_code_value", fake_bind)
    update = type("Update", (), {
        "effective_user": type("User", (), {"id": 123, "username": "alice"})(),
        "effective_message": object(),
    })()
    context = type("Context", (), {"args": ["bind_TG-ABCD-1234"], "user_data": {}})()

    await start(update, context)

    assert called["code"] == "TG-ABCD-1234"


def test_bound_panel_inline_keyboard_links_to_web_console():
    markup = build_panel_inline_keyboard(
        "https://moyin.cc/dashboard",
        {"bound": True, "user": {"status": "active"}},
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert any(
        button.text == "🌐 网页控制台"
        and button.url == "https://moyin.cc/dashboard"
        for button in buttons
    )


def test_bound_panel_keyboard_includes_recent_and_search_for_regular_users():
    markup = build_panel_inline_keyboard(
        "https://moyin.cc/dashboard",
        {
            "bound": True,
            "user": {"role": "user", "status": "active", "expiresAt": "2026-08-01T00:00:00+00:00"},
            "features": {
                "renewalEnabled": True,
                "passwordResetEnabled": True,
                "recentListeningEnabled": True,
            },
        },
    )
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "👤 账号与安全" in labels
    assert "🎁 积分与社区" in labels
    assert "📚 找书与收听" not in labels
    assert "📢 公告" not in labels
    assert "🎟️ 使用续期码" not in labels
    assert "🎧 最近收听" in labels
    assert "🔍 搜索有声书" in labels
    assert "👑 创建账户" not in labels


def test_progressive_submenus_expose_actions_and_a_way_home():
    data = {
        "bound": True,
        "user": {"status": "active", "expiresAt": "2026-08-01T00:00:00+00:00"},
        "features": {"renewalEnabled": True, "recentListeningEnabled": True},
    }
    account_labels = [
        button.text
        for row in build_account_keyboard(data).inline_keyboard
        for button in row
    ]
    assert "🎟️ 使用续期码" in account_labels
    assert "🔑 重置登录密码" in account_labels
    assert "‹ 返回首页" in account_labels


def test_help_keyboard_is_state_aware():
    unbound_labels = [
        button.text
        for row in build_help_keyboard({"bound": False}).inline_keyboard
        for button in row
    ]
    bound_labels = [
        button.text
        for row in build_help_keyboard(
            {"bound": True, "user": {"status": "active"}}
        ).inline_keyboard
        for button in row
    ]
    assert "👑 创建账户" in unbound_labels
    assert "🔗 绑定已有账号" in unbound_labels
    assert "👤 账号与安全" in bound_labels
    assert "🔍 搜索有声书" in bound_labels

    expired_labels = [
        button.text
        for row in build_help_keyboard(
            {"bound": True, "user": {"status": "expired"}}
        ).inline_keyboard
        for button in row
    ]
    assert "👤 账号与安全" in expired_labels
    assert "🔍 搜索有声书" not in expired_labels
    assert "🎁 积分与社区" not in expired_labels


def test_bind_flow_keyboard_links_directly_to_web_dashboard():
    buttons = [
        button
        for row in build_bind_keyboard("https://moyin.cc/dashboard").inline_keyboard
        for button in row
    ]
    assert any(
        button.text == "🌐 打开网页控制台"
        and button.url == "https://moyin.cc/dashboard"
        for button in buttons
    )


def test_recent_listening_is_capped_at_two_items():
    data = {
        "progress": [
            {"title": "第一本", "progressPercent": 25, "lastUpdate": "2026-07-17T00:00:00Z"},
            {"title": "第二本", "progressPercent": 50},
            {"title": "第三本", "progressPercent": 75},
        ]
    }
    text = format_recent_listening(data)
    assert "第一本" in text
    assert "第二本" in text
    assert "第三本" not in text
    assert "2026-07-17 08:00" in text

    panel = format_panel(
        {
            "bound": True,
            "user": {"username": "alice", "role": "user", "status": "active"},
            "recentListening": data["progress"],
        },
        telegram_id=1,
    )
    assert "第一本" in panel
    assert "第二本" in panel
    assert "第三本" not in panel


@pytest.mark.asyncio
async def test_regular_user_home_fetches_only_two_recent_items(monkeypatch):
    class FakeApi:
        requested_limit = None

        async def me(self, telegram_id):
            assert telegram_id == 123
            return {
                "bound": True,
                "user": {"role": "user", "status": "active"},
                "features": {"recentListeningEnabled": True},
            }

        async def recent_listening(self, telegram_id, *, limit):
            assert telegram_id == 123
            self.requested_limit = limit
            return {"progress": [{"title": "一"}, {"title": "二"}, {"title": "三"}]}

    fake = FakeApi()
    monkeypatch.setattr("app.user_handlers.API", fake)
    data = await _load_panel_data(123)
    assert fake.requested_limit == 2
    assert [item["title"] for item in data["recentListening"]] == ["一", "二"]


def test_search_results_and_request_notice():
    text = format_search_results(
        {
            "query": "三体",
            "items": [
                {
                    "title": "三体",
                    "author": "刘慈欣",
                    "narrator": "演播者",
                    "durationHours": 10.5,
                }
            ],
        }
    )
    assert "三体" in text
    assert "演播者" in text

    notice = format_request_notice()
    assert "有声书或播客" in notice
    assert "作品名称、作者或主播" in notice
    assert "只针对处理喜马拉雅" not in notice

    request_labels = [
        button.text
        for row in build_request_type_keyboard().inline_keyboard
        for button in row
    ]
    assert "📕 有声书" in request_labels
    assert "🎙 播客" in request_labels

    community_labels = [
            button.text
            for row in build_community_keyboard(
                {
                    "user": {"status": "active"},
                    "features": {"requestsEnabled": True},
                }
            ).inline_keyboard
        for button in row
    ]
    assert "📮 求书 / 播客" in community_labels


def test_admin_panel_requires_explicit_admin_visibility_and_admin_account():
    admin = {
        "bound": True,
        "user": {"role": "admin", "status": "active"},
        "features": {"adminEnabled": True},
    }
    hidden_labels = [
        button.text
        for row in build_panel_inline_keyboard(
            "https://moyin.cc/dashboard", admin
        ).inline_keyboard
        for button in row
    ]
    visible_labels = [
        button.text
        for row in build_panel_inline_keyboard(
            "https://moyin.cc/dashboard", admin, show_admin=True
        ).inline_keyboard
        for button in row
    ]
    normal_labels = [
        button.text
        for row in build_panel_inline_keyboard(
            "https://moyin.cc/dashboard",
            {"bound": True, "user": {"role": "user", "status": "active"}},
            show_admin=True,
        ).inline_keyboard
        for button in row
    ]
    assert "🛡️ Bot 管理台" not in hidden_labels
    assert "🛡️ Bot 管理台" in visible_labels
    assert "🛡️ Bot 管理台" not in normal_labels


def test_home_shows_admin_panel_only_for_allowlisted_bound_admin(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    data = {
        "bound": True,
        "user": {"role": "admin", "status": "active"},
        "features": {"adminEnabled": True},
    }

    allowed = [
        button.text
        for row in _panel_keyboard(data, telegram_id=123).inline_keyboard
        for button in row
    ]
    not_allowlisted = [
        button.text
        for row in _panel_keyboard(data, telegram_id=456).inline_keyboard
        for button in row
    ]

    assert "🛡️ Bot 管理台" in allowed
    assert "🛡️ Bot 管理台" not in not_allowlisted


def test_start_buttons_are_two_per_row_and_admin_expiry_is_allowlisted():
    regular = build_panel_inline_keyboard(
        "https://moyin.cc/dashboard",
        {
            "bound": True,
            "user": {"role": "user", "status": "active"},
            "features": {"recentListeningEnabled": True, "requestsEnabled": True},
        },
    )
    assert all(len(row) == 2 for row in regular.inline_keyboard)

    admin_data = {
        "bound": True,
        "telegramAdmin": True,
        "user": {
            "username": "admin",
            "role": "admin",
            "status": "active",
            "expiresAt": "2020-01-01T00:00:00Z",
        },
        "features": {"adminEnabled": True, "requestsEnabled": True},
    }
    admin = build_panel_inline_keyboard(
        "https://moyin.cc/dashboard", admin_data, show_admin=True
    )
    assert all(len(row) == 2 for row in admin.inline_keyboard)
    panel = format_panel(admin_data, telegram_id=8745546516)
    assert "有效期：白名单" in panel
    assert "0 天" not in panel


def test_admin_panel_prioritizes_actionable_lists_over_user_search():
    labels = [
        button.text for row in _admin_keyboard().inline_keyboard for button in row
    ]
    assert "👥 用户查询" not in labels
    assert "🎟️ 生成卡密" not in labels
    assert "📮 工单管理" in labels
    assert "⏰ 7天内到期" in labels
    assert "🟠 已到期" in labels
    assert "⛔ 已停用" in labels

    action_labels = [
        button.text
        for row in _user_keyboard(
            {"id": "u1", "status": "active", "expiresAt": "2026-08-01T00:00:00Z"}
        ).inline_keyboard
        for button in row
    ]
    assert "⏳ +7天" in action_labels
    assert "⏳ +30天" in action_labels
    assert "⛔ 停用" in action_labels
