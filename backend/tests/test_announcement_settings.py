"""Regression: announcement settings round-trip through the public-settings store."""
from sqlmodel import Session, SQLModel, create_engine

from app.services.settings import (
    DEFAULT_PUBLIC_SETTINGS,
    get_public_settings,
    update_public_settings,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_default_settings_expose_announcement_shape():
    ann = DEFAULT_PUBLIC_SETTINGS["announcement"]
    assert set(ann.keys()) == {"title", "body", "linkUrl", "linkLabel", "timeline"}
    assert ann["timeline"] == []


def test_default_settings_expose_client_config_shape():
    client = DEFAULT_PUBLIC_SETTINGS["client"]
    assert set(client.keys()) == {"serverUrl", "androidDownloadUrl", "iosGuideText", "desktopGuideText"}
    assert client["serverUrl"] == "https://listen.moyin.cc"


def test_announcement_timeline_round_trips():
    with _session() as session:
        update_public_settings(
            session,
            {"announcement": {"timeline": [
                {"date": "2026-06-08 15:39", "body": "充值倍率调整"},
                {"date": "2026-06-07 10:00", "body": "新增模型支持"},
            ]}},
        )
        stored = get_public_settings(session)
    tl = stored["announcement"]["timeline"]
    assert len(tl) == 2
    assert tl[0]["date"] == "2026-06-08 15:39"
    assert tl[0]["body"] == "充值倍率调整"
    # existing notice fields remain intact after a timeline-only patch
    assert "title" in stored["announcement"]


def test_announcement_patch_round_trips():
    with _session() as session:
        update_public_settings(
            session,
            {"announcement": {"title": "维护通知", "body": "周日凌晨维护", "linkUrl": "https://t.me/x", "linkLabel": "查看"}},
        )
        stored = get_public_settings(session)
    assert stored["announcement"]["title"] == "维护通知"
    assert stored["announcement"]["body"] == "周日凌晨维护"
    assert stored["announcement"]["linkUrl"] == "https://t.me/x"
    assert stored["announcement"]["linkLabel"] == "查看"


def test_legacy_settings_without_announcement_are_backfilled():
    with _session() as session:
        # Simulate an older stored blob that predates the announcement field.
        update_public_settings(session, {"siteName": "MoYin.CC"})
        stored = get_public_settings(session)
    # deep_merge against DEFAULT must inject the announcement shape.
    assert "announcement" in stored
    assert stored["announcement"]["title"] == ""


def test_unknown_legacy_fields_are_removed_when_settings_are_read_and_saved():
    with _session() as session:
        update_public_settings(
            session,
            {"features": {"renewal": True}, "legacyTopLevel": "discard-me"},
        )
        stored = get_public_settings(session)
        assert "renewal" not in stored["features"]
        assert "legacyTopLevel" not in stored

        update_public_settings(session, {"siteName": "Updated"})
        persisted = get_public_settings(session)
        assert "renewal" not in persisted["features"]
        assert "legacyTopLevel" not in persisted
