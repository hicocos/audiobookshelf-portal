import json
import logging
import time

import httpx
import pytest
from telegram.constants import ChatType
from telegram.constants import ChatMemberStatus

from app.main import (
    _http_error_detail,
    global_error_handler,
    guarded_handler,
)
from app.logging_config import JsonFormatter
from app.health import check_bot_health, write_bot_heartbeat
from app.notifications import notification_reply_markup, next_poll_delay
from app.user_handlers import callback_menu, text_menu, _redeem_points
from app.internal_api import InternalApi
from app.community import required_group_handler


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **_kwargs):
        self.replies.append(text)


class FakeChat:
    def __init__(self, chat_type):
        self.type = chat_type


class FakeUpdate:
    def __init__(self, chat_type=ChatType.PRIVATE):
        self.effective_chat = FakeChat(chat_type)
        self.effective_message = FakeMessage()
        self.effective_user = type("User", (), {"id": 123, "username": "alice"})()
        self.callback_query = None
        self.update_id = 987


class FakeContext:
    def __init__(self, error=None):
        self.error = error
        self.user_data = {}


def test_new_request_notification_has_direct_ticket_actions():
    markup = notification_reply_markup(
        {
            "kind": "media_request_admin",
            "dedupeKey": "media-request-admin:req-123:900",
        }
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "✅ 接受请求",
        "💬 回复工单",
        "🏁 结束工单",
    ]


def test_processed_request_notification_links_to_web_ticket_tab(monkeypatch):
    monkeypatch.setenv("PORTAL_PUBLIC_URL", "https://moyin.cc")
    markup = notification_reply_markup(
        {
            "kind": "media_request_status",
            "dedupeKey": "media-request-status:req-123:available",
        }
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["🌐 Web 端查看工单"]
    assert buttons[0].url == "https://moyin.cc/dashboard?tab=requests"


@pytest.mark.asyncio
async def test_callback_answer_timeout_does_not_abort_requested_action(monkeypatch):
    class Query:
        data = "request_start"
        message = FakeMessage()

        async def answer(self):
            from telegram.error import TimedOut

            raise TimedOut("telegram timeout")

    update = FakeUpdate()
    update.callback_query = Query()
    started = []

    async def fake_begin(_context, telegram_id, mode):
        started.append((telegram_id, mode))

    monkeypatch.setattr("app.user_handlers._begin_local_input", fake_begin)
    await callback_menu(update, FakeContext())
    assert started == [(123, "request_audiobook")]


@pytest.mark.asyncio
async def test_internal_api_retries_safe_read_once_after_network_error():
    api = InternalApi()
    attempts = 0

    class Client:
        async def request(self, method, path, **kwargs):
            nonlocal attempts
            attempts += 1
            request = httpx.Request(method, "http://internal" + path)
            if attempts == 1:
                raise httpx.ReadTimeout("slow read", request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

    api._client = Client()
    assert await api._request("GET", "/status") == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
async def test_write_timeout_warns_result_unknown_without_retry(monkeypatch):
    update = FakeUpdate()
    calls = 0

    async def fail_write(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout(
            "unknown result", request=httpx.Request("POST", "http://internal/redeem")
        )

    monkeypatch.setattr("app.user_handlers.API.redeem_points", fail_write)
    await _redeem_points(update, 1, "operation-123")
    assert calls == 1
    assert "结果待确认" in update.effective_message.replies[-1]
    assert "不要重复提交" in update.effective_message.replies[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "label"),
    [("expired", "已过期"), ("missing", "不存在"), ("completed", "已完成")],
)
async def test_text_menu_explains_inactive_flow_phase(monkeypatch, phase, label):
    update = FakeUpdate()
    update.effective_message.text = "任意输入"

    async def flow(_telegram_id):
        return {"active": False, "phase": phase}

    monkeypatch.setattr("app.user_handlers.API.flow", flow)
    await text_menu(update, FakeContext())
    assert label in update.effective_message.replies[-1]


@pytest.mark.asyncio
async def test_private_chat_guard_refuses_group_without_running_handler():
    update = FakeUpdate(ChatType.GROUP)
    called = False

    async def handler(_update, _context):
        nonlocal called
        called = True

    wrapped = guarded_handler(handler)
    await wrapped(update, FakeContext())

    assert called is False
    assert update.effective_message.replies == ["为保护邀请码、绑定码和账号信息，请私聊 Bot 使用此功能。"]


@pytest.mark.asyncio
async def test_private_chat_guard_allows_private_handler():
    update = FakeUpdate(ChatType.PRIVATE)
    called = False

    async def handler(_update, _context):
        nonlocal called
        called = True

    await guarded_handler(handler)(update, FakeContext())
    assert called is True


@pytest.mark.asyncio
async def test_bind_callback_bypasses_group_lookup_to_avoid_onboarding_deadlock():
    update = FakeUpdate()
    update.callback_query = type("Query", (), {"data": "bind_start"})()
    called = False

    async def handler(_update, _context):
        nonlocal called
        called = True

    class Api:
        async def community_config(self):
            raise AssertionError("binding callback must not query group membership")

    await required_group_handler(handler, Api())(update, FakeContext())
    assert called is True


class FakeCallbackQuery:
    data = "request_start"

    def __init__(self):
        self.answered = False
        self.message = FakeMessage()

    async def answer(self, *_args, **_kwargs):
        self.answered = True


@pytest.mark.asyncio
async def test_group_gate_acknowledges_blocked_callback_and_explains_grace_deadline():
    update = FakeUpdate()
    update.callback_query = FakeCallbackQuery()
    update.effective_message = update.callback_query.message

    async def handler(_update, _context):
        raise AssertionError("blocked callback must not reach the action handler")

    class Api:
        async def community_config(self):
            return {"enabled": True, "groupId": "-1004319046591", "inviteUrl": "https://t.me/moyinclub"}

        async def report_membership(self, *_args, **_kwargs):
            return {"bound": True, "status": "grace", "graceExpiresAt": "2026-07-24T00:00:00Z"}

    class Bot:
        async def get_chat_member(self, **_kwargs):
            return type("Member", (), {"status": ChatMemberStatus.LEFT})()

    context = FakeContext()
    context.bot = Bot()
    await required_group_handler(handler, Api())(update, context)

    assert update.callback_query.answered is True
    assert "Bot 功能已暂停" in update.effective_message.replies[-1]
    assert "媒体账号宽限期至" in update.effective_message.replies[-1]


@pytest.mark.asyncio
async def test_non_member_in_account_grace_is_still_blocked_from_bot_features():
    update = FakeUpdate()
    called = False

    async def handler(_update, _context):
        nonlocal called
        called = True

    class Api:
        async def community_config(self):
            return {
                "enabled": True,
                "groupId": "-1004319046591",
                "inviteUrl": "https://t.me/moyinclub",
            }

        async def report_membership(self, *_args, **_kwargs):
            return {
                "bound": True,
                "status": "grace",
                "graceExpiresAt": "2026-07-24T00:00:00Z",
            }

    class Bot:
        async def get_chat_member(self, **_kwargs):
            return type("Member", (), {"status": ChatMemberStatus.LEFT})()

    context = FakeContext()
    context.bot = Bot()
    context.bot_data = {}
    await required_group_handler(handler, Api())(update, context)

    assert called is False
    assert "Bot 功能已暂停" in update.effective_message.replies[-1]
    assert "媒体账号宽限期至 2026-07-24T00:00:00Z" in update.effective_message.replies[-1]


@pytest.mark.asyncio
async def test_a04_grandfathered_user_bypasses_group_gate_under_new_users_only_scope():
    update = FakeUpdate()
    called = False

    async def handler(_update, _context):
        nonlocal called
        called = True

    class Api:
        async def community_config(self):
            return {
                "enabled": True,
                "scope": "new_users_only",
                "groupId": "-1004319046591",
                "inviteUrl": "https://t.me/moyinclub",
            }

        async def community_eligibility(self, telegram_id):
            assert telegram_id == 123
            return {"bound": True, "applicable": False, "scope": "new_users_only"}

    class Bot:
        async def get_chat_member(self, **_kwargs):
            raise AssertionError("grandfathered users must not be checked or blocked")

    context = FakeContext()
    context.bot = Bot()
    context.bot_data = {}
    await required_group_handler(handler, Api())(update, context)

    assert called is True
    assert update.effective_message.replies == []


@pytest.mark.asyncio
async def test_global_error_handler_returns_safe_message():
    update = FakeUpdate()
    await global_error_handler(update, FakeContext(RuntimeError("secret internal detail")))
    assert update.effective_message.replies
    reply = update.effective_message.replies[-1]
    assert "请求失败" in reply
    assert "secret internal detail" not in reply


def test_invalid_error_json_uses_fallback_and_records_debug(caplog):
    request = httpx.Request("POST", "http://internal/api/internal/tg/bind")
    response = httpx.Response(400, content=b"not-json", request=request)
    error = httpx.HTTPStatusError("bad response", request=request, response=response)

    with caplog.at_level(logging.DEBUG):
        detail = _http_error_detail(error, "安全提示")

    assert detail == "安全提示"
    assert "not JSON" in caplog.text


def test_api_error_detail_never_leaks_raw_backend_english():
    request = httpx.Request("POST", "http://internal/api/internal/tg/bind")
    response = httpx.Response(
        400,
        json={"detail": "User account is disabled by upstream service"},
        request=request,
    )
    error = httpx.HTTPStatusError("bad response", request=request, response=response)

    assert _http_error_detail(error, "绑定失败，请稍后重试。") == "绑定失败，请稍后重试。"


@pytest.mark.asyncio
async def test_handler_logs_include_update_id_as_json(caplog):
    update = FakeUpdate()

    async def handler(_update, _context):
        logging.getLogger("test.bot").info("handled")

    with caplog.at_level(logging.INFO):
        await guarded_handler(handler)(update, FakeContext())

    record = next(record for record in caplog.records if record.name == "test.bot")
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "handled"
    assert payload["update_id"] == 987


def test_json_formatter_redacts_telegram_credentials():
    record = logging.LogRecord(
        name="test.bot",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="POST https://api.telegram.org/bot123456:secret_TOKEN/getMe",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "secret_TOKEN" not in payload["message"]
    assert "/bot[REDACTED]/getMe" in payload["message"]
    assert payload["timestamp"].endswith("+08:00")


def test_bot_health_requires_a_recent_heartbeat(tmp_path):
    state_path = tmp_path / "bot-health.json"
    with pytest.raises(SystemExit):
        check_bot_health(str(state_path), max_age_seconds=60)

    write_bot_heartbeat(str(state_path))
    check_bot_health(str(state_path), max_age_seconds=60)

    state_path.write_text(
        json.dumps(
            {
                "healthy": True,
                "telegramHealthy": True,
                "apiHealthy": True,
                "checkedAt": time.time() - 61,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="stale"):
        check_bot_health(str(state_path), max_age_seconds=60)


def test_notification_polling_backs_off_when_idle_and_resets_on_work():
    assert next_poll_delay(5, base_seconds=5, had_work=False, failed=False) == 10
    assert next_poll_delay(40, base_seconds=5, had_work=False, failed=False) == 60
    assert next_poll_delay(60, base_seconds=5, had_work=True, failed=False) == 5
    assert next_poll_delay(5, base_seconds=5, had_work=False, failed=True) == 10
