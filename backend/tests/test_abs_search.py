import json

import pytest
import respx
from httpx import Response

from app.abs_client import AudiobookshelfClient


@pytest.mark.asyncio
async def test_search_library_uses_abs_search_endpoint_and_unwraps_book_results():
    with respx.mock:
        route = respx.get("https://abs.example/api/libraries/lib-1/search").mock(
            return_value=Response(
                200,
                json={
                    "book": [
                        {
                            "libraryItem": {
                                "id": "item-1",
                                "libraryId": "lib-1",
                                "media": {"metadata": {"title": "三体"}},
                            }
                        }
                    ],
                    "authors": [],
                },
            )
        )
        async with AudiobookshelfClient("https://abs.example", "token") as client:
            items = await client.search_library("lib-1", "三体", limit=8)

    assert items[0]["id"] == "item-1"
    assert route.calls.last.request.url.params["q"] == "三体"
    assert route.calls.last.request.url.params["limit"] == "8"
    assert json.loads(route.calls.last.request.content or b"null") is None
