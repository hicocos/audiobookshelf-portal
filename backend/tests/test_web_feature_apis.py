import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import AppSetting, Code, PortalUser, utcnow
from app.security import create_access_token


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PortalUser(
                id="user-id",
                username="listener",
                password_hash="hash",
                abs_user_id="abs-listener",
                abs_username="listener",
                telegram_id="123456",
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        session.add(
            PortalUser(
                id="expired-id",
                username="expired-listener",
                password_hash="hash",
                abs_user_id="abs-expired",
                abs_username="expired-listener",
                telegram_id="654321",
                status="expired",
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        session.add(
            PortalUser(
                id="admin-id",
                username="admin",
                password_hash="hash",
                role="admin",
                abs_username="admin",
            )
        )
        session.add(
            AppSetting(
                key="public_settings",
                value_json=json.dumps({"telegram": {"leaderboardEnabled": True}}),
            )
        )
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def headers(subject: str, role: str):
    return {"Authorization": f"Bearer {create_access_token(subject=subject, role=role)}"}


def test_user_can_check_in_create_referral_and_submit_request():
    client = make_client()
    try:
        user_headers = headers("user-id", "user")
        checked = client.post("/api/me/checkin", headers=user_headers)
        assert checked.status_code == 200
        assert checked.json()["pointsAwarded"] >= 1

        rewards = client.get("/api/me/rewards", headers=user_headers)
        assert rewards.status_code == 200
        assert rewards.json()["balance"] == checked.json()["balance"]

        opted_in = client.post(
            "/api/me/leaderboard/opt-in",
            headers=user_headers,
            json={"enabled": True},
        )
        assert opted_in.status_code == 200
        leaderboard = client.get("/api/me/leaderboard", headers=user_headers)
        assert leaderboard.status_code == 200
        assert leaderboard.json()["entries"][0]["displayName"] == "l*****r"

        referral = client.post("/api/me/referrals", headers=user_headers)
        assert referral.status_code == 200
        assert referral.json()["code"]

        created = client.post(
            "/api/me/requests",
            headers=user_headers,
            json={"kind": "book", "title": "测试有声书", "details": "作者测试"},
        )
        assert created.status_code == 200
        listed = client.get("/api/me/requests", headers=user_headers)
        assert listed.json()["items"][0]["title"] == "测试有声书"
    finally:
        app.dependency_overrides.clear()


def test_admin_can_review_and_update_request():
    client = make_client()
    try:
        user_headers = headers("user-id", "user")
        admin_headers = headers("admin-id", "admin")
        created = client.post(
            "/api/me/requests",
            headers=user_headers,
            json={"kind": "podcast", "title": "测试播客"},
        ).json()["item"]

        overview = client.get("/api/admin/operations/overview", headers=admin_headers)
        assert overview.status_code == 200
        assert overview.json()["pendingRequests"] == 1

        updated = client.post(
            f"/api/admin/operations/requests/{created['id']}",
            headers=admin_headers,
            json={"status": "available", "note": "已经入库"},
        )
        assert updated.status_code == 200
        assert updated.json()["item"]["status"] == "available"
    finally:
        app.dependency_overrides.clear()


def test_open_request_limit_is_enforced_and_resolved_slot_can_be_reused():
    client = make_client()
    try:
        user_headers = headers("user-id", "user")
        admin_headers = headers("admin-id", "admin")
        created_ids = []
        for index in range(3):
            response = client.post(
                "/api/me/requests",
                headers=user_headers,
                json={"kind": "book", "title": f"请求 {index + 1}"},
            )
            assert response.status_code == 200
            created_ids.append(response.json()["item"]["id"])

        limited = client.post(
            "/api/me/requests",
            headers=user_headers,
            json={"kind": "book", "title": "请求 4"},
        )
        assert limited.status_code == 429

        resolved = client.post(
            f"/api/admin/operations/requests/{created_ids[0]}",
            headers=admin_headers,
            json={"status": "available", "note": "已入库"},
        )
        assert resolved.status_code == 200
        replacement = client.post(
            "/api/me/requests",
            headers=user_headers,
            json={"kind": "book", "title": "补位请求"},
        )
        assert replacement.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_expired_user_is_limited_to_recovery_features():
    client = make_client()
    try:
        expired_headers = headers("expired-id", "user")
        assert client.get("/api/me", headers=expired_headers).status_code == 200
        assert client.post("/api/me/checkin", headers=expired_headers).status_code == 403
        assert client.post("/api/me/referrals", headers=expired_headers).status_code == 403
        assert client.get("/api/me/requests", headers=expired_headers).status_code == 403
        assert client.post(
            "/api/me/requests",
            headers=headers("user-id", "user"),
            json={"kind": "book", "title": "   "},
        ).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_me_returns_capabilities_for_active_expired_and_admin_users():
    client = make_client()
    try:
        active = client.get("/api/me", headers=headers("user-id", "user"))
        assert active.status_code == 200
        assert active.json()["capabilities"] == {
            "canListen": True,
            "canRenew": True,
            "canChangePassword": True,
            "canCheckin": True,
            "canRedeemPoints": True,
            "canRefer": True,
            "canRequest": True,
            "canViewLeaderboard": True,
            "canAdmin": False,
            "unavailableReasons": {},
        }

        expired = client.get("/api/me", headers=headers("expired-id", "user"))
        assert expired.status_code == 200
        assert expired.json()["capabilities"] == {
            "canListen": False,
            "canRenew": True,
            "canChangePassword": True,
            "canCheckin": False,
            "canRedeemPoints": False,
            "canRefer": False,
            "canRequest": False,
            "canViewLeaderboard": False,
            "canAdmin": False,
            "unavailableReasons": {
                "listen": "账号已到期，请先续期恢复收听。",
                "checkin": "账号已到期，请先续期后再签到。",
                "redeemPoints": "账号已到期，请先续期后再使用积分。",
                "refer": "账号已到期，请先续期后再邀请好友。",
                "request": "账号已到期，请先续期后再提交内容请求。",
                "leaderboard": "账号已到期，请先续期后再查看排行榜。",
                "admin": "当前账号没有管理权限。",
            },
        }

        admin = client.get("/api/me", headers=headers("admin-id", "admin"))
        assert admin.status_code == 200
        assert admin.json()["capabilities"]["canAdmin"] is True
        assert admin.json()["capabilities"]["canListen"] is True
    finally:
        app.dependency_overrides.clear()


def test_me_capabilities_follow_feature_switches():
    client = make_client()
    try:
        response = client.get("/api/me", headers=headers("user-id", "user"))
        assert response.status_code == 200
        assert response.json()["capabilities"]["canViewLeaderboard"] is True

        with next(app.dependency_overrides[get_session]()) as session:
            setting = session.get(AppSetting, "public_settings")
            setting.value_json = json.dumps(
                {
                    "telegram": {
                        "renewalEnabled": False,
                        "checkinEnabled": False,
                        "pointsRedemptionEnabled": False,
                        "referralEnabled": False,
                        "requestsEnabled": False,
                        "leaderboardEnabled": False,
                    }
                }
            )
            session.add(Code(code="RENEW-CLOSED", type="renew", duration_days=30))
            session.add(setting)
            session.commit()

        disabled = client.get("/api/me", headers=headers("user-id", "user"))
        assert disabled.status_code == 200
        capabilities = disabled.json()["capabilities"]
        assert capabilities["canListen"] is True
        assert capabilities["canRenew"] is False
        assert capabilities["canCheckin"] is False
        assert capabilities["canRedeemPoints"] is False
        assert capabilities["canRefer"] is False
        assert capabilities["canRequest"] is False
        assert capabilities["canViewLeaderboard"] is False
        assert capabilities["unavailableReasons"]["renew"] == "续期功能当前未开放。"
        assert capabilities["unavailableReasons"]["checkin"] == "签到功能当前未开放。"

        renewal = client.post(
            "/api/me/redeem",
            headers=headers("user-id", "user"),
            json={"code": "RENEW-CLOSED"},
        )
        assert renewal.status_code == 403
        assert renewal.json()["detail"] == "续期功能当前未开放。"
        with next(app.dependency_overrides[get_session]()) as session:
            code = session.exec(select(Code).where(Code.code == "RENEW-CLOSED")).one()
            user = session.get(PortalUser, "user-id")
            assert code.used_count == 0
            assert user.expires_at is not None
            assert (user.expires_at.date() - utcnow().date()).days >= 29
    finally:
        app.dependency_overrides.clear()


def test_user_can_export_personal_data_without_secrets():
    client = make_client()
    try:
        response = client.get("/api/me/export", headers=headers("user-id", "user"))
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        payload = response.json()
        assert payload["account"]["username"] == "listener"
        serialized = json.dumps(payload)
        assert "password_hash" not in serialized
        assert "token_hash" not in serialized
    finally:
        app.dependency_overrides.clear()


def test_admin_broadcast_requires_preview_count_and_queues_audited_notifications():
    client = make_client()
    try:
        admin_headers = headers("admin-id", "admin")
        preview = client.get(
            "/api/admin/operations/broadcast/preview?audience=active",
            headers=admin_headers,
        )
        assert preview.status_code == 200
        assert preview.json()["count"] == 1
        assert preview.json()["sample"] == ["listener"]

        stale = client.post(
            "/api/admin/operations/broadcast",
            headers=admin_headers,
            json={"audience": "active", "message": "维护通知", "confirmCount": 2, "idempotencyKey": "broadcast-stale"},
        )
        assert stale.status_code == 409

        queued = client.post(
            "/api/admin/operations/broadcast",
            headers=admin_headers,
            json={"audience": "active", "message": "维护通知", "confirmCount": 1, "idempotencyKey": "broadcast-once"},
        )
        assert queued.status_code == 200
        assert queued.json()["queued"] == 1
        replay = client.post(
            "/api/admin/operations/broadcast",
            headers=admin_headers,
            json={"audience": "active", "message": "维护通知", "confirmCount": 1, "idempotencyKey": "broadcast-once"},
        )
        assert replay.status_code == 200
        assert replay.json()["idempotentReplay"] is True
        notifications = client.get(
            "/api/admin/operations/notifications?status=pending",
            headers=admin_headers,
        ).json()["items"]
        assert len(notifications) == 1
        assert notifications[0]["kind"] == "admin_broadcast"
        audit = client.get(
            "/api/admin/operations/audit?limit=10", headers=admin_headers
        ).json()["items"]
        assert audit[0]["action"] == "admin.telegram_broadcast.enqueue"
    finally:
        app.dependency_overrides.clear()
