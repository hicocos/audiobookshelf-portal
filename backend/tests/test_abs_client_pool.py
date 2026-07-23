from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.abs_client import AudiobookshelfClient
from app.routers.auth import close_shared_abs_clients, get_abs_client_factory


@pytest.mark.asyncio
async def test_client_reuses_the_same_http_pool_across_context_entries(monkeypatch):
    created: list[AsyncMock] = []

    def factory(*args, **kwargs):
        client = AsyncMock(spec=AsyncClient)
        created.append(client)
        return client

    monkeypatch.setattr("app.abs_client.httpx.AsyncClient", factory)
    client = AudiobookshelfClient("https://abs.example", "token", keep_open=True)

    async with client:
        first = client.client
    async with client:
        second = client.client

    assert first is second
    assert len(created) == 1
    created[0].aclose.assert_not_awaited()
    await client.aclose()
    created[0].aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_application_shutdown_closes_shared_abs_clients(monkeypatch):
    client = AsyncMock(spec=AudiobookshelfClient)
    monkeypatch.setattr("app.routers.auth._shared_abs_client", lambda *_args: client)

    get_abs_client_factory()
    await close_shared_abs_clients()

    client.aclose.assert_awaited_once()
