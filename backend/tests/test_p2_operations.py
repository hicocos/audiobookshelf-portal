import os
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import AuditLog, MediaRequest, PortalUser, TelegramGroupMembership, TelegramNotification, utcnow
from app.security import create_access_token


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    now = utcnow()
    with Session(engine) as session:
        session.add(PortalUser(id="user", username="listener", abs_username="listener", password_hash="x", telegram_id="42"))
        session.add(PortalUser(id="admin", username="admin", abs_username="admin", password_hash="x", role="admin"))
        for index in range(3):
            session.add(MediaRequest(id=f"r{index}", portal_user_id="user", kind="book", title=f"书 {index}", status="pending", open_slot=index + 1, created_at=now))
        for index in range(3):
            session.add(TelegramNotification(dedupe_key=f"n:{index}", telegram_id="42", kind="test", message="m", created_at=now))
        session.add(TelegramGroupMembership(portal_user_id="user", telegram_id="42", group_id="g", created_at=now, updated_at=now, last_checked_at=now))
        session.add(AuditLog(actor_username=None, action="admin.test", target_type=None, target_id=None, detail_json=None, created_at=now))
        session.commit()

    def override():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = override
    token = create_access_token(subject="admin", role="admin")
    return TestClient(app), engine, {"Authorization": f"Bearer {token}"}


def test_same_user_normalized_duplicate_requires_explicit_version_confirmation():
    client, _engine, headers = make_client()
    try:
        duplicate = client.post("/api/me/requests", headers={"Authorization": f"Bearer {create_access_token(subject='user', role='user')}"}, json={"title": "  书 ０  "})
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "duplicate_title"
        confirmed = client.post("/api/me/requests", headers={"Authorization": f"Bearer {create_access_token(subject='user', role='user')}"}, json={"title": "书 ０", "confirmDifferentVersion": True})
        assert confirmed.status_code == 429  # duplicate was not inserted; existing three-slot limit still applies
    finally:
        app.dependency_overrides.clear()


def test_operations_lists_are_totalled_paginated_and_stably_ordered():
    client, _engine, headers = make_client()
    try:
        requests = client.get("/api/admin/operations/requests?limit=2&offset=1", headers=headers).json()
        assert requests["total"] == 3
        assert [item["id"] for item in requests["items"]] == ["r1", "r0"]
        notifications = client.get("/api/admin/operations/notifications?limit=2&offset=1", headers=headers).json()
        assert notifications["total"] == 3
        assert len(notifications["items"]) == 2
        memberships = client.get("/api/admin/operations/memberships?limit=1&offset=0", headers=headers).json()
        assert memberships["total"] == 1
        audit = client.get("/api/admin/operations/audit?action=admin.test&limit=1&offset=0", headers=headers).json()
        assert audit["total"] == 1
        assert audit["items"][0]["detail"] is None
    finally:
        app.dependency_overrides.clear()


def test_request_status_label_and_notification_message_are_consistent():
    client, engine, headers = make_client()
    try:
        updated = client.post("/api/admin/operations/requests/r0", headers=headers, json={"status": "available", "note": "完整版已入库"})
        assert updated.status_code == 200
        assert updated.json()["item"]["statusLabel"] == "已上架"
        with Session(engine) as session:
            notice = session.exec(select(TelegramNotification).where(TelegramNotification.kind == "media_request_status")).one()
            assert "状态已更新：已上架" in notice.message
            assert "管理员备注：完整版已入库" in notice.message
            assert session.exec(select(AuditLog).where(AuditLog.action == "admin.media_request.available")).first() is not None
    finally:
        app.dependency_overrides.clear()


def test_public_version_endpoint_exposes_build_metadata(monkeypatch):
    monkeypatch.setenv("BUILD_VERSION", "2026.07.23")
    monkeypatch.setenv("BUILD_COMMIT", "abc123")
    monkeypatch.setenv("BUILD_DATE", "2026-07-23T00:00:00Z")
    response = TestClient(app).get("/api/public/version")
    assert response.status_code == 200
    assert response.json() == {"version": "2026.07.23", "commit": "abc123", "builtAt": "2026-07-23T00:00:00Z"}
