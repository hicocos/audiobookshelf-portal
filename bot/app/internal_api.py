from typing import Any

import httpx

from app.config import BotSettings


class InternalApi:
    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or BotSettings()
        self.base_url = self.settings.web_internal_api_base.rstrip("/")
        self.headers = {"Authorization": f"Bearer {self.settings.telegram_bot_internal_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=20.0) as client:
            response = await client.request(method, path, **kwargs)
            if response.status_code == 404:
                return {"bound": False}
            response.raise_for_status()
            return response.json() if response.content else {}

    async def bind(self, *, code: str, telegram_id: int, telegram_username: str | None) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/bind",
            json={"code": code, "telegramId": str(telegram_id), "telegramUsername": telegram_username},
        )

    async def register(
        self,
        *,
        username: str,
        invite_code: str,
        telegram_id: int,
        telegram_username: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register",
            json={
                "username": username,
                "inviteCode": invite_code,
                "telegramId": str(telegram_id),
                "telegramUsername": telegram_username,
            },
        )

    async def check_register_invite(self, *, invite_code: str, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register/invite/check",
            json={"inviteCode": invite_code, "telegramId": str(telegram_id)},
        )

    async def check_register_username(self, *, username: str, invite_code: str, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register/username/check",
            json={"username": username, "inviteCode": invite_code, "telegramId": str(telegram_id)},
        )

    async def me(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/me/{telegram_id}")

    async def open(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("POST", "/api/internal/tg/open", json={"telegramId": str(telegram_id)})

    async def library_summary(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/library/summary/{telegram_id}")

    async def search(self, telegram_id: int, query: str, limit: int = 8) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/internal/tg/library/search/{telegram_id}",
            params={"q": query, "limit": limit},
        )
