import pytest
import respx
from httpx import Response

from app.abs_client import AudiobookshelfClient


@pytest.mark.asyncio
async def test_ping_returns_true_for_success():
    with respx.mock:
        respx.get("https://abs.example/ping").mock(return_value=Response(200, json={"success": True}))
        async with AudiobookshelfClient("https://abs.example", "token") as client:
            assert await client.ping() is True


@pytest.mark.asyncio
async def test_status_returns_server_status():
    with respx.mock:
        respx.get("https://abs.example/status").mock(
            return_value=Response(200, json={"isInit": True, "language": "zh-cn"})
        )
        async with AudiobookshelfClient("https://abs.example/", "token") as client:
            assert await client.status() == {"isInit": True, "language": "zh-cn"}


@pytest.mark.asyncio
async def test_list_libraries_sends_bearer_token_and_returns_libraries():
    with respx.mock:
        route = respx.get("https://abs.example/api/libraries").mock(
            return_value=Response(200, json={"libraries": [{"id": "lib-1", "name": "内测"}]})
        )
        async with AudiobookshelfClient("https://abs.example", "secret-token") as client:
            libraries = await client.list_libraries()

    assert libraries == [{"id": "lib-1", "name": "内测"}]
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_list_users_supports_common_response_shapes():
    with respx.mock:
        respx.get("https://abs.example/api/users").mock(
            return_value=Response(200, json={"users": [{"id": "u1", "username": "root"}]})
        )
        async with AudiobookshelfClient("https://abs.example", "token") as client:
            assert await client.list_users() == [{"id": "u1", "username": "root"}]


@pytest.mark.asyncio
async def test_get_current_user_returns_authenticated_token_owner():
    with respx.mock:
        route = respx.get("https://abs.example/api/me").mock(
            return_value=Response(200, json={"user": {"id": "root-1", "username": "root"}})
        )
        async with AudiobookshelfClient("https://abs.example", "secret-token") as client:
            user = await client.get_current_user()

    assert user == {"id": "root-1", "username": "root"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_get_library_item_returns_metadata_for_progress_title():
    with respx.mock:
        route = respx.get("https://abs.example/api/items/book-1").mock(
            return_value=Response(
                200,
                json={
                    "id": "book-1",
                    "media": {"metadata": {"title": "灵境行者"}},
                },
            )
        )
        async with AudiobookshelfClient("https://abs.example", "secret-token") as client:
            item = await client.get_library_item("book-1")

    assert item["media"]["metadata"]["title"] == "灵境行者"
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_create_user_posts_payload_and_unwraps_user_response():
    with respx.mock:
        route = respx.post("https://abs.example/api/users").mock(
            return_value=Response(200, json={"user": {"id": "u2", "username": "alice"}})
        )
        async with AudiobookshelfClient("https://abs.example", "token") as client:
            user = await client.create_user(
                username="alice",
                password="pw",
                permissions={"download": False, "accessAllLibraries": True},
            )

    assert user == {"id": "u2", "username": "alice"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer token"
    import json

    payload = json.loads(route.calls.last.request.content)
    assert payload["username"] == "alice"
    assert payload["permissions"]["download"] is False


@pytest.mark.asyncio
async def test_update_and_delete_user_call_expected_endpoints():
    with respx.mock:
        patch_route = respx.patch("https://abs.example/api/users/u2").mock(
            return_value=Response(200, json={"user": {"id": "u2", "isActive": True}})
        )
        delete_route = respx.delete("https://abs.example/api/users/u2").mock(
            return_value=Response(200, json={"success": True})
        )
        async with AudiobookshelfClient("https://abs.example", "token") as client:
            updated = await client.update_user("u2", {"isActive": True})
            deleted = await client.delete_user("u2")

    assert updated == {"id": "u2", "isActive": True}
    assert deleted is True
    assert patch_route.called
    assert delete_route.called
