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
    format_bind_success,
    format_help,
    format_media_requests,
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
from app.admin_handlers import (
    _admin_keyboard,
    _format_request,
    _format_request_list,
    _format_stats,
    _request_keyboard,
    _request_list_keyboard,
    _user_keyboard,
)
from app.user_handlers import (
    _load_panel_data,
    _panel_keyboard,
    parse_audiobook_request,
    request_command,
    search_command,
    start,
)
from app.main import build_command_menu, requires_group_membership


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
    descriptions = {item.command: item.description for item in commands}
    assert descriptions["request"] == "求有声书"
    assert descriptions["requests"] == "查看有声书工单"


def test_binding_entry_points_bypass_group_gate_but_user_features_do_not():
    assert requires_group_membership("start") is False
    assert requires_group_membership("bind") is False
    assert requires_group_membership("register") is False
    assert requires_group_membership("help") is False
    assert requires_group_membership("checkin") is True
    assert requires_group_membership("request") is True


@pytest.mark.asyncio
async def test_request_command_enters_single_audiobook_flow(monkeypatch):
    started = {}

    async def fake_begin(context, telegram_id, mode):
        started.update(telegram_id=telegram_id, mode=mode)

    class Message:
        reply = None

        async def reply_text(self, text, *, reply_markup):
            self.reply = (text, reply_markup)

    monkeypatch.setattr("app.user_handlers._begin_local_input", fake_begin)
    message = Message()
    update = type(
        "Update",
        (),
        {
            "effective_user": type("User", (), {"id": 123, "username": "alice"})(),
            "effective_message": message,
        },
    )()
    context = type("Context", (), {"args": [], "user_data": {}})()

    await request_command(update, context)

    assert started == {"telegram_id": 123, "mode": "request_audiobook"}
    assert "求有声书" in message.reply[0]
    assert "播客" not in message.reply[0]
    buttons = [
        button
        for row in message.reply[1].inline_keyboard
        for button in row
    ]
    assert [button.text for button in buttons] == ["取消"]


@pytest.mark.asyncio
async def test_search_callback_without_command_args_enters_search_flow(monkeypatch):
    started = {}

    async def fake_begin(context, telegram_id, mode):
        started.update(telegram_id=telegram_id, mode=mode)

    class Message:
        reply = None

        async def reply_text(self, text, *, reply_markup):
            self.reply = (text, reply_markup)

    monkeypatch.setattr("app.user_handlers._begin_local_input", fake_begin)
    message = Message()
    update = type("Update", (), {
        "effective_user": type("User", (), {"id": 123, "username": "alice"})(),
        "effective_message": message,
    })()
    context = type("Context", (), {"args": None, "user_data": {}})()

    await search_command(update, context)

    assert started == {"telegram_id": 123, "mode": "library_search"}
    assert "搜索有声书" in message.reply[0]


@pytest.mark.asyncio
async def test_blank_audiobook_request_keeps_input_flow_active(monkeypatch):
    cancelled: list[int] = []

    async def fake_flow(_telegram_id):
        return {"active": True, "kind": "input", "step": "request_audiobook"}

    async def fake_cancel(telegram_id):
        cancelled.append(telegram_id)
        return {"cleared": True}

    class Message:
        text = "   "
        reply = None

        async def reply_text(self, text, *, reply_markup):
            self.reply = (text, reply_markup)

    monkeypatch.setattr("app.user_handlers.API.flow", fake_flow)
    monkeypatch.setattr("app.user_handlers.API.cancel_flow", fake_cancel)
    message = Message()
    update = type(
        "Update",
        (),
        {
            "effective_user": type("User", (), {"id": 123, "username": "alice"})(),
            "effective_message": message,
        },
    )()
    context = type("Context", (), {"user_data": {"input_mode": "request_audiobook"}})()

    from app.user_handlers import text_menu

    await text_menu(update, context)

    assert cancelled == []
    assert context.user_data["input_mode"] == "request_audiobook"
    assert "信息不完整" in message.reply[0]


@pytest.mark.asyncio
async def test_admin_request_reply_flow_survives_missing_local_context(monkeypatch):
    handled = {}

    async def fake_flow(_telegram_id):
        return {
            "active": True,
            "kind": "input",
            "step": "admin_request_reply:req-123",
        }

    async def fake_reply(update, context, request_id, text):
        handled.update(request_id=request_id, text=text)

    class Message:
        text = "请补充作者信息"

    monkeypatch.setattr("app.user_handlers.API.flow", fake_flow)
    monkeypatch.setattr("app.admin_handlers.handle_admin_request_reply", fake_reply)
    update = type(
        "Update",
        (),
        {
            "effective_user": type("User", (), {"id": 123, "username": "admin"})(),
            "effective_message": Message(),
        },
    )()
    context = type("Context", (), {"user_data": {}})()

    from app.user_handlers import text_menu

    await text_menu(update, context)

    assert handled == {"request_id": "req-123", "text": "请补充作者信息"}


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
    assert "目前仅提供喜马拉雅 FM 上的资源" in notice
    assert "请提供详细信息，否则不予处理" in notice
    assert "包括但不限于" in notice
    assert "平台：" in notice
    assert "作品名称：" in notice
    assert "演播者：" in notice
    assert "是否完结：" in notice
    assert "目前集数：" in notice
    assert "播客" not in notice

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
    assert "📮 求有声书" in community_labels
    assert not any("播客" in label for label in community_labels)

    history = format_media_requests(
        {
            "items": [
                {"kind": "book", "title": "三体", "status": "pending"},
                {"kind": "podcast", "title": "旧工单", "status": "accepted"},
            ]
        }
    )
    assert "三体" in history
    assert "旧工单" in history
    assert "播客" not in history


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
    assert labels == ["📮 工单管理", "🔄 刷新工单"]

    stats = _format_stats({"pendingRequests": 3})
    assert "Telegram 工单管理" in stats
    assert "待处理工单：3" in stats
    assert "正常用户" not in stats
    assert "到期用户" not in stats
    assert "群组宽限" not in stats
    assert "定时任务" not in stats

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


def test_admin_request_card_is_human_readable_and_has_three_actions():
    item = {
        "id": "req-123",
        "username": "alice",
        "title": "斗破苍穹",
        "details": "平台：喜马拉雅 FM\n演播者：暮玖\n是否完结：否\n目前集数：1200",
        "status": "pending",
        "createdAt": "2026-07-19T06:00:00Z",
    }
    text = _format_request(item)
    assert "工单编号：req-123" in text
    assert "提交用户：alice" in text
    assert "作品名称：斗破苍穹" in text
    assert "状态：待处理" in text
    assert "pending" not in text

    buttons = [
        button for row in _request_keyboard("req-123").inline_keyboard for button in row
    ]
    assert [button.text for button in buttons] == ["✅ 接受请求", "💬 回复工单", "🏁 结束工单"]
    assert [button.callback_data for button in buttons] == [
        "adm_req:accepted:req-123",
        "adm_req_reply:req-123",
        "adm_req:available:req-123",
    ]


def test_audiobook_request_accepts_free_form_content():
    assert parse_audiobook_request("333366") == ("333366", None)
    assert parse_audiobook_request(
        "平台：喜马拉雅 FM\n作品名称：斗破苍穹\n演播者：暮玖\n是否完结：否\n目前集数：1200"
    ) == (
        "斗破苍穹",
        "平台：喜马拉雅 FM\n演播者：暮玖\n是否完结：否\n目前集数：1200",
    )
    assert parse_audiobook_request("平台：蜻蜓 FM\n作品名称：斗破苍穹") == (
        "斗破苍穹",
        "平台：蜻蜓 FM",
    )


def test_admin_request_list_is_one_compact_message_with_selection_buttons():
    items = [
        {"id": "req-1", "username": "alice", "title": "斗破苍穹", "status": "pending"},
        {"id": "req-2", "username": "bob", "title": "三体", "status": "accepted"},
    ]
    text = _format_request_list(items)
    assert "待处理工单（2）" in text
    assert "1. [待处理] 斗破苍穹 · alice" in text
    assert "2. [已接受] 三体 · bob" in text

    buttons = [
        button for row in _request_list_keyboard(items).inline_keyboard for button in row
    ]
    assert [button.text for button in buttons] == ["1 · 斗破苍穹", "2 · 三体", "🔄 刷新工单"]
    assert [button.callback_data for button in buttons[:2]] == [
        "adm_req_view:req-1",
        "adm_req_view:req-2",
    ]
