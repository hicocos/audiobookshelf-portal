
from app.handlers import (
    SimpleRateLimiter,
    build_main_keyboard,
    build_panel_inline_keyboard,
    format_bind_success,
    format_help,
    format_library_summary,
    format_me,
    format_panel,
    format_register_success,
    format_search_results,
    parse_bind_code,
    parse_register_args,
)


def test_parse_bind_code_requires_code():
    assert parse_bind_code("/bind") is None
    assert parse_bind_code("/bind TG-ABCD-1234") == "TG-ABCD-1234"


def test_format_bind_success_mentions_username_and_next_commands():
    text = format_bind_success({"user": {"username": "alice", "status": "active"}})
    assert "绑定成功" in text
    assert "alice" in text
    assert "/me" in text


def test_format_me_handles_unbound_and_bound_users():
    assert "还没有绑定" in format_me({"bound": False})
    text = format_me({
        "bound": True,
        "serverUrl": "https://moyin.cc",
        "user": {
            "username": "alice",
            "status": "active",
            "expiresAt": None,
            "absUsername": "alice",
        },
    })
    assert "alice" in text
    assert "永久有效" in text
    assert "https://moyin.cc" in text


def test_format_search_results_truncates_and_escapes():
    data = {
        "bound": True,
        "query": "三体",
        "items": [
            {"title": "三体_[特别版]", "author": "刘慈欣", "narrator": "演播", "durationHours": 12.3},
            {"title": "黑暗森林", "author": "刘慈欣", "narrator": "", "durationHours": 18},
        ],
    }
    text = format_search_results(data)
    assert "三体" in text
    assert "特别版" in text
    assert "刘慈欣" in text


def test_format_library_summary():
    text = format_library_summary({"bound": True, "count": 1, "libraries": [{"name": "内测", "mediaType": "book"}]})
    assert "媒体库" in text
    assert "内测" in text


def test_format_help_lists_commands():
    text = format_help()
    assert "/bind" in text
    assert "/search" in text


def test_parse_register_args_requires_username_and_invite_code():
    assert parse_register_args("/register") is None
    assert parse_register_args("/register alice INVITE-123") == ("alice", "INVITE-123")


def test_format_register_success_returns_one_time_password_warning():
    text = format_register_success({
        "user": {"username": "alice", "expiresAt": None},
        "oneTimePassword": "secret-pass",
        "serverUrl": "https://moyin.cc",
    })
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
    assert "欢迎进入" in text
    assert "7974849843" in text
    assert "未注册" in text

    bound = format_panel({
        "bound": True,
        "serverUrl": "https://listen.moyin.cc",
        "user": {"username": "alice", "status": "active", "expiresAt": None},
    }, telegram_id=1)
    assert "alice" in bound
    assert "已注册" in bound
    assert "https://listen.moyin.cc" in bound


def test_build_main_keyboard_contains_account_and_web_console_buttons():
    markup = build_main_keyboard("https://moyin.cc/dashboard")
    labels = [button.text if hasattr(button, "text") else str(button) for row in markup.keyboard for button in row]
    assert "🎟️ 使用注册码" in labels
    assert "👑 创建账户" in labels
    assert "🌐 网页控制台" in labels


def test_build_panel_inline_keyboard_links_to_web_console():
    markup = build_panel_inline_keyboard("https://moyin.cc/dashboard")
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert any(button.text == "🌐 网页控制台" and button.url == "https://moyin.cc/dashboard" for button in buttons)
