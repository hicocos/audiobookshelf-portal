import json
import logging

import httpx
import pytest
from telegram.constants import ChatType

from app.main import (
    _http_error_detail,
    global_error_handler,
    guarded_handler,
)
from app.logging_config import JsonFormatter


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
