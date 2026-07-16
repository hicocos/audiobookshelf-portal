import pytest
from telegram.constants import ChatType

from app.main import ensure_private_chat, global_error_handler, guarded_handler


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
