import argparse
import asyncio
from urllib.parse import quote
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings


class AudiobookshelfClient:
    """Small Audiobookshelf REST client.

    MVP intentionally implements only read-only methods. User creation/update methods
    must be added after write endpoints are confirmed with a disposable test user.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 20.0,
        *,
        keep_open: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.keep_open = keep_open
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AudiobookshelfClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 5.0)),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self.keep_open:
            await self.aclose()

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("AudiobookshelfClient must be used as an async context manager")
        return self._client

    async def _get(self, path: str) -> Any:
        response = await self.client.get(path)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    async def ping(self) -> bool:
        data = await self._get("/ping")
        return bool(isinstance(data, Mapping) and data.get("success") is True)

    async def status(self) -> dict[str, Any]:
        data = await self._get("/status")
        if not isinstance(data, dict):
            raise TypeError("Unexpected Audiobookshelf status response")
        return data

    async def list_libraries(self) -> list[dict[str, Any]]:
        data = await self._get("/api/libraries")
        if isinstance(data, Mapping) and isinstance(data.get("libraries"), list):
            return list(data["libraries"])
        if isinstance(data, list):
            return data
        raise TypeError("Unexpected Audiobookshelf libraries response")

    async def list_users(self) -> list[dict[str, Any]]:
        data = await self._get("/api/users")
        if isinstance(data, Mapping) and isinstance(data.get("users"), list):
            return list(data["users"])
        if isinstance(data, list):
            return data
        raise TypeError("Unexpected Audiobookshelf users response")

    async def get_current_user(self) -> dict[str, Any]:
        data = await self._get("/api/me")
        if isinstance(data, Mapping) and isinstance(data.get("user"), dict):
            return dict(data["user"])
        if isinstance(data, dict) and data.get("id"):
            return data
        raise TypeError("Unexpected Audiobookshelf current user response")

    async def get_user(self, user_id: str) -> dict[str, Any]:
        data = await self._get(f"/api/users/{quote(user_id, safe='')}")
        if isinstance(data, Mapping) and isinstance(data.get("user"), dict):
            return dict(data["user"])
        if isinstance(data, dict) and data.get("id"):
            return data
        raise TypeError("Unexpected Audiobookshelf user response")

    async def get_library_item(self, item_id: str) -> dict[str, Any]:
        data = await self._get(f"/api/items/{quote(item_id, safe='')}")
        if isinstance(data, Mapping) and isinstance(data.get("libraryItem"), dict):
            return dict(data["libraryItem"])
        if isinstance(data, dict) and data.get("id"):
            return data
        raise TypeError("Unexpected Audiobookshelf library item response")

    async def list_library_items(self, library_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
        data = await self._get(f"/api/libraries/{quote(library_id, safe='')}/items?limit={int(limit)}")
        if isinstance(data, Mapping) and isinstance(data.get("results"), list):
            return list(data["results"])
        if isinstance(data, Mapping) and isinstance(data.get("items"), list):
            return list(data["items"])
        if isinstance(data, list):
            return data
        raise TypeError("Unexpected Audiobookshelf library items response")

    async def search_library(
        self,
        library_id: str,
        query: str,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"/api/libraries/{quote(library_id, safe='')}/search",
            params={"q": query, "limit": int(limit)},
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, Mapping):
            raise TypeError("Unexpected Audiobookshelf search response")
        items: list[dict[str, Any]] = []
        for entry in data.get("book", []):
            if isinstance(entry, Mapping) and isinstance(entry.get("libraryItem"), Mapping):
                items.append(dict(entry["libraryItem"]))
        return items

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        permissions: dict[str, Any] | None = None,
        type: str = "user",
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"username": username, "password": password, "type": type}
        if permissions is not None:
            payload["permissions"] = permissions
        if is_active is not None:
            payload["isActive"] = is_active
        response = await self.client.post("/api/users", json=payload)
        response.raise_for_status()
        data = response.json() if response.content else {}
        if isinstance(data, Mapping) and isinstance(data.get("user"), dict):
            return dict(data["user"])
        if isinstance(data, dict) and data.get("id"):
            return data
        raise TypeError("Unexpected Audiobookshelf create user response")

    async def update_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.patch(f"/api/users/{quote(user_id, safe='')}", json=payload)
        response.raise_for_status()
        data = response.json() if response.content else {}
        if isinstance(data, Mapping) and isinstance(data.get("user"), dict):
            return dict(data["user"])
        if isinstance(data, dict):
            return data
        raise TypeError("Unexpected Audiobookshelf update user response")

    async def delete_user(self, user_id: str) -> bool:
        response = await self.client.delete(f"/api/users/{quote(user_id, safe='')}")
        response.raise_for_status()
        return True


async def smoke_readonly() -> None:
    settings = Settings()
    async with AudiobookshelfClient(
        settings.audiobookshelf_url,
        settings.audiobookshelf_admin_token,
    ) as client:
        print("ping", await client.ping())
        status = await client.status()
        print("status", {key: status.get(key) for key in ["isInit", "language"]})
        libraries = await client.list_libraries()
        print(
            "libraries",
            len(libraries),
            [{"id": item.get("id"), "name": item.get("name")} for item in libraries[:5]],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-readonly", action="store_true")
    args = parser.parse_args()
    if args.smoke_readonly:
        asyncio.run(smoke_readonly())


if __name__ == "__main__":
    main()
