from typing import Any

import httpx

from app.config import BotSettings


class InternalApi:
    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or BotSettings()
        self.base_url = self.settings.web_internal_api_base.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.settings.telegram_bot_internal_token}"
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=20.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._get_client().request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError):
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                raise
            response = await self._get_client().request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/public/health/live")

    async def start_flow(
        self, telegram_id: int, *, kind: str, step: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/flow/start",
            json={"telegramId": str(telegram_id), "kind": kind, "step": step},
        )

    async def flow(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/flow/{telegram_id}")

    async def cancel_flow(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/internal/tg/flow/{telegram_id}")

    async def bind(
        self, *, code: str, telegram_id: int, telegram_username: str | None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/bind",
            json={
                "code": code,
                "telegramId": str(telegram_id),
                "telegramUsername": telegram_username,
            },
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

    async def check_register_invite(
        self, *, invite_code: str, telegram_id: int
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register/invite/check",
            json={"inviteCode": invite_code, "telegramId": str(telegram_id)},
        )

    async def check_register_username(
        self, *, username: str, telegram_id: int
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register/username/check",
            json={"username": username, "telegramId": str(telegram_id)},
        )

    async def confirm_register(
        self,
        *,
        telegram_id: int,
        telegram_username: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/register/confirm",
            json={
                "telegramId": str(telegram_id),
                "telegramUsername": telegram_username,
            },
        )

    async def me(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/me/{telegram_id}")

    async def recent_listening(
        self, telegram_id: int, *, limit: int = 2
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 2))
        return await self._request(
            "GET",
            f"/api/internal/tg/recent/{telegram_id}",
            params={"limit": safe_limit},
        )

    async def search(
        self, telegram_id: int, query: str, *, limit: int = 8
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/internal/tg/library/search/{telegram_id}",
            params={"q": query, "limit": max(1, min(limit, 8))},
        )

    async def renew_preview(self, telegram_id: int, code: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/renew/preview",
            json={"telegramId": str(telegram_id), "code": code},
        )

    async def renew_confirm(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/renew/confirm",
            json={"telegramId": str(telegram_id)},
        )

    async def password_reset(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/password-reset",
            json={"telegramId": str(telegram_id)},
        )

    async def claim_notifications(self, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._request(
            "POST",
            "/api/internal/tg/notifications/claim",
            json={"limit": limit},
        )
        items = data.get("items")
        return items if isinstance(items, list) else []

    async def acknowledge_notification(
        self,
        notification_id: str,
        *,
        success: bool,
        error: str | None = None,
        retry_after_seconds: int | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/internal/tg/notifications/{notification_id}/ack",
            json={
                "success": success,
                "error": error,
                "retryAfterSeconds": retry_after_seconds,
                "retryable": retryable,
            },
        )

    async def rewards(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/rewards/{telegram_id}")

    async def checkin(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/internal/tg/checkin", json={"telegramId": str(telegram_id)}
        )

    async def redeem_points(
        self, telegram_id: int, days: int, idempotency_key: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/points/redeem",
            json={
                "telegramId": str(telegram_id),
                "days": days,
                "idempotencyKey": idempotency_key,
            },
        )

    async def leaderboard(self) -> dict[str, Any]:
        return await self._request("GET", "/api/internal/tg/leaderboard")

    async def leaderboard_opt_in(
        self, telegram_id: int, enabled: bool
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/leaderboard/opt-in",
            json={"telegramId": str(telegram_id), "enabled": enabled},
        )

    async def referral_invite(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/referral/invite",
            json={"telegramId": str(telegram_id)},
        )

    async def media_requests(self, telegram_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/internal/tg/requests/{telegram_id}")

    async def create_media_request(
        self,
        telegram_id: int,
        *,
        title: str,
        details: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/requests",
            json={
                "telegramId": str(telegram_id),
                "title": title,
                "details": details,
            },
        )

    async def community_config(self) -> dict[str, Any]:
        return await self._request("GET", "/api/internal/tg/community/config")

    async def community_eligibility(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/internal/tg/community/eligibility/{telegram_id}",
        )

    async def report_membership(
        self, telegram_id: int, *, group_id: str, is_member: bool
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/community/report",
            json={
                "telegramId": str(telegram_id),
                "groupId": group_id,
                "isMember": is_member,
            },
        )

    async def admin_stats(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/stats",
            json={"telegramId": str(telegram_id)},
        )

    async def admin_search_users(self, telegram_id: int, query: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/users/search",
            json={"telegramId": str(telegram_id), "query": query},
        )

    async def admin_list_users(
        self, telegram_id: int, category: str, *, limit: int = 10
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/users/list",
            json={
                "telegramId": str(telegram_id),
                "category": category,
                "limit": max(1, min(limit, 20)),
            },
        )

    async def admin_action_preview(
        self,
        telegram_id: int,
        *,
        action: str,
        target_user_id: str,
        extend_days: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/actions/preview",
            json={
                "telegramId": str(telegram_id),
                "action": action,
                "targetUserId": target_user_id,
                "extendDays": extend_days,
            },
        )

    async def admin_action_confirm(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/actions/confirm",
            json={"telegramId": str(telegram_id)},
        )

    async def admin_requests(self, telegram_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/internal/tg/admin/requests/list",
            json={"telegramId": str(telegram_id)},
        )

    async def admin_update_request(
        self,
        telegram_id: int,
        request_id: str,
        *,
        status: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/internal/tg/admin/requests/{request_id}",
            json={"telegramId": str(telegram_id), "status": status, "note": note},
        )

    async def admin_reply_request(
        self,
        telegram_id: int,
        request_id: str,
        message: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/internal/tg/admin/requests/{request_id}/reply",
            json={"telegramId": str(telegram_id), "message": message},
        )
