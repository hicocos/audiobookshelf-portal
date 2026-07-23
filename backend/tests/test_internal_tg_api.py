from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import AuditLog, Code, MediaRequest, PortalUser, TelegramNotification, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import hash_password, verify_password
from app.services.telegram_binding import create_bind_token


class FakeAbsClient:
    def __init__(self):
        self.created = []
        self.libraries = [{"id": "lib1", "name": "内测", "mediaType": "book"}]
        self.user = {
            "id": "abs-alice",
            "username": "alice",
            "isActive": True,
            "permissions": {"accessAllLibraries": True},
            "mediaProgress": [],
        }
        self.items = [
            {
                "id": "book1",
                "libraryId": "lib1",
                "media": {
                    "duration": 3600,
                    "numTracks": 12,
                    "metadata": {
                        "title": "捞尸人",
                        "authorName": "纯洁滴小龙",
                        "narratorName": "方片K",
                    },
                },
                "addedAt": 1710000000000,
            },
            {
                "id": "book2",
                "libraryId": "lib1",
                "media": {
                    "duration": 7200,
                    "numTracks": 20,
                    "metadata": {
                        "title": "三体",
                        "authorName": "刘慈欣",
                        "narratorName": "演播者",
                    },
                },
                "addedAt": 1710000000000,
            },
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def list_libraries(self):
        return self.libraries

    async def get_user(self, user_id):
        return dict(self.user, id=user_id)

    async def list_library_items(self, library_id, *, limit=8):
        return self.items[:limit]

    async def search_library(self, library_id, query, *, limit=8):
        needle = query.casefold()
        return [
            item
            for item in self.items
            if needle in str(item.get("media", {}).get("metadata", {}).get("title", "")).casefold()
        ][:limit]

    async def create_user(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "abs-created", "username": kwargs["username"]}

    async def update_user(self, user_id, payload):
        self.user.update(payload)
        self.user["id"] = user_id
        return dict(self.user)

    async def get_library_item(self, item_id):
        return next(item for item in self.items if item["id"] == item_id)


def make_client(monkeypatch, *, internal_token="internal-secret"):
    monkeypatch.setenv("TELEGRAM_BOT_INTERNAL_TOKEN", internal_token)
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake_abs)
    return TestClient(app), engine, fake_abs, internal_token


def teardown_client():
    app.dependency_overrides.clear()


def auth_headers(token="internal-secret"):
    return {"Authorization": f"Bearer {token}"}


def seed_user(
    session: Session,
    *,
    telegram_id: str | None = None,
    status="active",
    abs_user_id="abs-alice",
    username="alice",
    role="user",
) -> PortalUser:
    user = PortalUser(
        username=username,
        username_normalized=username.casefold(),
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id=abs_user_id,
        abs_username=username,
        expires_at=utcnow() + timedelta(days=5),
        status=status,
        role=role,
        telegram_id=telegram_id,
        telegram_username=f"{username}_tg" if telegram_id else None,
        telegram_bound_at=utcnow() if telegram_id else None,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_internal_tg_api_requires_configured_bearer_token(monkeypatch):
    client, _engine, _fake_abs, _token = make_client(monkeypatch)
    try:
        missing = client.get("/api/internal/tg/me/123")
        assert missing.status_code == 401

        wrong = client.get("/api/internal/tg/me/123", headers=auth_headers("wrong"))
        assert wrong.status_code == 403
    finally:
        teardown_client()


def test_internal_tg_api_returns_503_when_internal_token_not_configured(monkeypatch):
    client, _engine, _fake_abs, _token = make_client(monkeypatch, internal_token="")
    try:
        response = client.get("/api/internal/tg/me/123", headers=auth_headers("anything"))
        assert response.status_code == 503
    finally:
        teardown_client()


def test_internal_bind_consumes_web_bind_code(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            user = seed_user(session)
            code, _bind_token = create_bind_token(session, user)
            user_id = user.id

        response = client.post(
            "/api/internal/tg/bind",
            headers=auth_headers(token),
            json={"code": code, "telegramId": "987654321", "telegramUsername": "alice_tg"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["bound"] is True
        assert body["user"]["username"] == "alice"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.telegram_id == "987654321"
    finally:
        teardown_client()


def test_internal_me_returns_bound_false_for_unknown_telegram_id(monkeypatch):
    client, _engine, _fake_abs, token = make_client(monkeypatch)
    try:
        response = client.get("/api/internal/tg/me/unknown", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["bound"] is False
        assert response.json()["features"]["renewalEnabled"] is True
    finally:
        teardown_client()


def test_internal_open_is_idempotent_for_existing_abs_account(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")

        response = client.post(
            "/api/internal/tg/open",
            headers=auth_headers(token),
            json={"telegramId": "987654321"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["opened"] is True
        assert body["alreadyOpen"] is True
        assert body["user"]["absUsername"] == "alice"
        assert fake_abs.created == []
    finally:
        teardown_client()


def test_internal_search_returns_bound_user_visible_library_items(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")

        response = client.get(
            "/api/internal/tg/library/search/987654321?q=捞尸&limit=5",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["bound"] is True
        assert body["count"] == 1
        assert body["items"][0]["title"] == "捞尸人"
        assert body["items"][0]["author"] == "纯洁滴小龙"
    finally:
        teardown_client()


def test_internal_register_creates_portal_and_abs_user_bound_to_telegram(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            session.add(Code(code="INVITE-TG", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/internal/tg/register",
            headers=auth_headers(token),
            json={"telegramId": "987654321", "telegramUsername": "alice_tg", "username": "alice_tg_user", "inviteCode": "INVITE-TG"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] is True
        assert body["bound"] is True
        assert body["oneTimePassword"]
        assert body["user"]["username"] == "alice_tg_user"
        assert fake_abs.created and fake_abs.created[0]["username"] == "alice_tg_user"
        with Session(engine) as session:
            saved = session.get(PortalUser, body["user"]["id"])
            assert saved is not None
            assert saved.telegram_id == "987654321"
            assert saved.telegram_username == "alice_tg"
            assert saved.telegram_binding_required is True
            code = session.exec(select(Code).where(Code.code == "INVITE-TG")).one()
            assert code.used_count == 1
    finally:
        teardown_client()


def test_internal_register_rejects_when_telegram_already_bound(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")
            session.add(Code(code="INVITE-TG", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/internal/tg/register",
            headers=auth_headers(token),
            json={"telegramId": "987654321", "telegramUsername": "alice_tg", "username": "new_user", "inviteCode": "INVITE-TG"},
        )

        assert response.status_code == 409
        assert fake_abs.created == []
    finally:
        teardown_client()


def test_binding_activates_web_registered_pending_account(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            user = seed_user(session, status="pending", abs_user_id="abs-alice")
            user.telegram_binding_required = True
            user.created_at = utcnow() - timedelta(days=2)
            user.expires_at = user.created_at + timedelta(days=5)
            session.add(user)
            session.commit()
            code, _ = create_bind_token(session, user)
            user_id = user.id
            old_expiry = user.expires_at

        response = client.post(
            "/api/internal/tg/bind",
            headers=auth_headers(token),
            json={"code": code, "telegramId": "987654321", "telegramUsername": "alice_tg"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["user"]["status"] == "active"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "active"
            assert saved.telegram_id == "987654321"
            assert saved.expires_at > old_expiry + timedelta(days=1)
        assert fake_abs.user["isActive"] is True
    finally:
        teardown_client()


def test_persistent_registration_flow_survives_across_requests(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            session.add(Code(code="FLOW-INVITE", type="register", duration_days=14))
            session.commit()

        invite = client.post(
            "/api/internal/tg/register/invite/check",
            headers=auth_headers(token),
            json={"telegramId": "42", "inviteCode": "FLOW-INVITE"},
        )
        assert invite.status_code == 200, invite.text
        flow = client.get("/api/internal/tg/flow/42", headers=auth_headers(token)).json()
        assert flow["step"] == "register_username"

        username = client.post(
            "/api/internal/tg/register/username/check",
            headers=auth_headers(token),
            json={"telegramId": "42", "username": "flow_user"},
        )
        assert username.status_code == 200, username.text
        confirmed = client.post(
            "/api/internal/tg/register/confirm",
            headers=auth_headers(token),
            json={"telegramId": "42", "telegramUsername": "flow_tg"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["user"]["username"] == "flow_user"
        assert fake_abs.created[-1]["username"] == "flow_user"
        assert client.get("/api/internal/tg/flow/42", headers=auth_headers(token)).json() == {
            "active": False
        }
    finally:
        teardown_client()


def test_input_flow_can_persist_audiobook_request_step(monkeypatch):
    client, _engine, _fake_abs, token = make_client(monkeypatch)
    try:
        started = client.post(
            "/api/internal/tg/flow/start",
            headers=auth_headers(token),
            json={
                "telegramId": "42",
                "kind": "input",
                "step": "request_audiobook",
            },
        )
        assert started.status_code == 200, started.text
        flow = client.get("/api/internal/tg/flow/42", headers=auth_headers(token))
        assert flow.status_code == 200
        assert flow.json()["kind"] == "input"
        assert flow.json()["step"] == "request_audiobook"
    finally:
        teardown_client()


def test_renewal_preview_and_confirm_reactivates_expired_account(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            user = seed_user(session, telegram_id="42", status="expired")
            user.expires_at = utcnow() - timedelta(days=1)
            session.add(user)
            session.add(Code(code="RENEW-30", type="renew", duration_days=30))
            session.commit()

        preview = client.post(
            "/api/internal/tg/renew/preview",
            headers=auth_headers(token),
            json={"telegramId": "42", "code": "RENEW-30"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["durationDays"] == 30
        confirmed = client.post(
            "/api/internal/tg/renew/confirm",
            headers=auth_headers(token),
            json={"telegramId": "42"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["user"]["status"] == "active"
        assert confirmed.json()["upstreamReactivated"] is True
        assert fake_abs.user["isActive"] is True
    finally:
        teardown_client()


def test_telegram_password_reset_link_is_one_time_and_syncs_abs(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            user = seed_user(session, telegram_id="42")
            user_id = user.id

        created = client.post(
            "/api/internal/tg/password-reset",
            headers=auth_headers(token),
            json={"telegramId": "42"},
        )
        assert created.status_code == 200, created.text
        reset_url = created.json()["url"]
        assert "/reset-password#token=" in reset_url
        assert "?token=" not in reset_url
        raw_token = reset_url.split("#token=", 1)[1]
        checked = client.post(
            "/api/public/password-reset/validate", json={"token": raw_token}
        )
        assert checked.status_code == 200
        assert client.get(f"/api/public/password-reset?token={raw_token}").status_code == 405
        consumed = client.post(
            "/api/public/password-reset",
            json={"token": raw_token, "newPassword": "Brand-new-pass18"},
        )
        assert consumed.status_code == 200, consumed.text
        assert fake_abs.user["password"] == "Brand-new-pass18"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert verify_password("Brand-new-pass18", saved.password_hash)
        reused = client.post(
            "/api/public/password-reset",
            json={"token": raw_token, "newPassword": "Another-new-pass"},
        )
        assert reused.status_code == 400
    finally:
        teardown_client()


def test_recent_listening_and_notification_delivery_contract(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="42")
            session.add(
                TelegramNotification(
                    dedupe_key="test:42:1",
                    telegram_id="42",
                    kind="expiry_reminder",
                    message="你的账号即将到期。",
                )
            )
            session.commit()
        fake_abs.user["mediaProgress"] = [
            {
                "id": "progress-1",
                "libraryItemId": "book1",
                "progress": 0.5,
                "lastUpdate": 1710000000000,
            }
        ]
        recent = client.get(
            "/api/internal/tg/recent/42",
            headers=auth_headers(token),
        )
        assert recent.status_code == 200, recent.text
        assert recent.json()["progress"][0]["title"] == "捞尸人"
        assert recent.json()["progress"][0]["progressPercent"] == 50.0

        claimed = client.post(
            "/api/internal/tg/notifications/claim",
            headers=auth_headers(token),
            json={"limit": 10},
        )
        assert claimed.status_code == 200
        item = claimed.json()["items"][0]
        assert item["telegramId"] == "42"
        acked = client.post(
            f"/api/internal/tg/notifications/{item['id']}/ack",
            headers=auth_headers(token),
            json={"success": True},
        )
        assert acked.json()["status"] == "sent"
    finally:
        teardown_client()


def test_tg_admin_requires_allowlist_and_bound_portal_admin(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "900,901")
    try:
        with Session(engine) as session:
            seed_user(
                session,
                telegram_id="900",
                abs_user_id="abs-admin",
                username="admin",
                role="admin",
            )
            seed_user(
                session,
                telegram_id="901",
                abs_user_id="abs-normal",
                username="normal",
            )

        missing_allowlist = client.post(
            "/api/internal/tg/admin/stats",
            headers=auth_headers(token),
            json={"telegramId": "999"},
        )
        assert missing_allowlist.status_code == 403
        normal_user = client.post(
            "/api/internal/tg/admin/stats",
            headers=auth_headers(token),
            json={"telegramId": "901"},
        )
        assert normal_user.status_code == 403
        admin = client.post(
            "/api/internal/tg/admin/stats",
            headers=auth_headers(token),
            json={"telegramId": "900"},
        )
        assert admin.status_code == 200, admin.text
        assert admin.json()["admin"] == {"username": "admin", "role": "admin"}
        assert set(admin.json()["users"]) == {"active", "expired", "disabled"}
        expiring = client.post(
            "/api/internal/tg/admin/users/list",
            headers=auth_headers(token),
            json={"telegramId": "900", "category": "expiring", "limit": 10},
        )
        assert expiring.status_code == 200, expiring.text
        assert [item["username"] for item in expiring.json()["users"]] == ["normal"]
        invalid_category = client.post(
            "/api/internal/tg/admin/users/list",
            headers=auth_headers(token),
            json={"telegramId": "900", "category": "all"},
        )
        assert invalid_category.status_code == 422
    finally:
        teardown_client()


def test_tg_admin_user_action_requires_preview_and_is_audited(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "900")
    try:
        with Session(engine) as session:
            seed_user(
                session,
                telegram_id="900",
                abs_user_id="abs-admin",
                username="admin",
                role="admin",
            )
            target = seed_user(
                session,
                telegram_id="42",
                abs_user_id="abs-bob",
                username="bob",
            )
            target_id = target.id

        no_preview = client.post(
            "/api/internal/tg/admin/actions/confirm",
            headers=auth_headers(token),
            json={"telegramId": "900"},
        )
        assert no_preview.status_code == 409
        search = client.post(
            "/api/internal/tg/admin/users/search",
            headers=auth_headers(token),
            json={"telegramId": "900", "query": "bo"},
        )
        assert search.status_code == 200
        assert search.json()["users"][0]["id"] == target_id
        preview = client.post(
            "/api/internal/tg/admin/actions/preview",
            headers=auth_headers(token),
            json={
                "telegramId": "900",
                "action": "disable",
                "targetUserId": target_id,
            },
        )
        assert preview.status_code == 200, preview.text
        confirmed = client.post(
            "/api/internal/tg/admin/actions/confirm",
            headers=auth_headers(token),
            json={"telegramId": "900"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["user"]["status"] == "disabled"
        assert fake_abs.user["isActive"] is False
        replay = client.post(
            "/api/internal/tg/admin/actions/confirm",
            headers=auth_headers(token),
            json={"telegramId": "900"},
        )
        assert replay.status_code == 409
        with Session(engine) as session:
            target = session.get(PortalUser, target_id)
            assert target.status == "disabled"
            audits = session.exec(
                select(AuditLog).where(AuditLog.target_id == target_id)
            ).all()
            assert [item.action for item in audits] == ["telegram.admin.user.disable"]
    finally:
        teardown_client()


def test_media_request_lifecycle_notifies_admin_and_requester(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "900")
    try:
        with Session(engine) as session:
            seed_user(
                session,
                telegram_id="900",
                abs_user_id="abs-admin",
                username="admin",
                role="admin",
            )
            seed_user(
                session,
                telegram_id="42",
                abs_user_id="abs-requester",
                username="requester",
            )

        created = client.post(
            "/api/internal/tg/requests",
            headers=auth_headers(token),
            json={
                "telegramId": "42",
                "title": "测试有声书",
                "details": "希望收录完整版",
            },
        )
        assert created.status_code == 200, created.text
        request_id = created.json()["item"]["id"]
        claimed = client.post(
            "/api/internal/tg/notifications/claim",
            headers=auth_headers(token),
            json={"limit": 10},
        )
        admin_notice = next(
            item for item in claimed.json()["items"] if item["kind"] == "media_request_admin"
        )
        assert admin_notice["dedupeKey"] == f"media-request-admin:{request_id}:900"
        assert "工单编号" in admin_notice["message"]
        assert "提交用户：requester" in admin_notice["message"]
        assert "作品名称：测试有声书" in admin_notice["message"]
        listed = client.post(
            "/api/internal/tg/admin/requests/list",
            headers=auth_headers(token),
            json={"telegramId": "900"},
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["username"] == "requester"
        replied = client.post(
            f"/api/internal/tg/admin/requests/{request_id}/reply",
            headers=auth_headers(token),
            json={"telegramId": "900", "message": "请补充演播者信息"},
        )
        assert replied.status_code == 200, replied.text
        updated = client.post(
            f"/api/internal/tg/admin/requests/{request_id}",
            headers=auth_headers(token),
            json={"telegramId": "900", "status": "available", "note": "已入库"},
        )
        assert updated.status_code == 200, updated.text
        with Session(engine) as session:
            item = session.get(MediaRequest, request_id)
            assert item.status == "available"
            assert item.admin_note == "已入库"
            assert item.resolved_at is not None
            notices = session.exec(select(TelegramNotification)).all()
            assert {(notice.telegram_id, notice.kind) for notice in notices} == {
                ("900", "media_request_admin"),
                ("42", "media_request_reply"),
                ("42", "media_request_status"),
            }
            status_notice = next(
                notice for notice in notices if notice.kind == "media_request_status"
            )
            assert status_notice.message == (
                "您的工单已经处理。详细信息请到 Web 端查看。"
            )
            reply = next(
                notice for notice in notices if notice.kind == "media_request_reply"
            )
            assert "请补充演播者信息" in reply.message
    finally:
        teardown_client()
