import json
from hashlib import sha256
from copy import deepcopy
from typing import Any

from sqlmodel import Session

from app.models import AppSetting, AuditLog, utcnow

PUBLIC_SETTINGS_KEY = "public_settings"


def settings_revision(settings: dict[str, Any]) -> str:
    canonical = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()

DEFAULT_PUBLIC_SETTINGS: dict[str, Any] = {
    "siteName": "MoYin.CC",
    "tagline": "安静的声音栖地",
    "copy": {
        "heroKicker": "AUDIO ISLAND",
        "heroTitle": "MoYin.CC",
        "heroSubtitle": "安静的声音栖地",
        "primaryCta": "申请访问",
        "secondaryCta": "进入账号中心",
        "notice": "一个轻量、安静、专注的音频内容入口。",
    },
    "links": {
        "libraryUrl": "",
        "supportUrl": "",
        "announcementUrl": "",
    },
    "client": {
        "serverUrl": "https://listen.moyin.cc",
        "androidDownloadUrl": "https://mikupan.com/s/AOrU0",
        "iosGuideText": "打开 App Store，搜索 EchoShelf 并安装。",
        "desktopGuideText": "电脑端教程暂未固定，建议优先使用手机或平板客户端。",
    },
    "announcement": {
        "title": "",
        "body": "",
        "linkUrl": "",
        "linkLabel": "",
        "timeline": [],
    },
    "features": {
        "registration": True,
        "showLibraryEntry": True,
        "showSupportEntry": False,
        "showAnnouncements": True,
    },
    "operations": {
        "inactivityAutoDisable": False,
        "inactiveDays": 30,
        "newUserGraceDays": 7,
        "lastInactivityCheckAt": None,
        "lastInactivityDisabled": 0,
    },
    "telegram": {
        "renewalEnabled": True,
        "passwordResetEnabled": True,
        "recentListeningEnabled": True,
        "announcementsEnabled": True,
        "lifecycleNotificationsEnabled": True,
        "adminEnabled": True,
        "groupMembershipEnabled": False,
        "groupPolicyScope": "new_users_only",
        "requiredGroupId": "",
        "requiredGroupInviteUrl": "",
        "groupGraceHours": 72,
        "requestsEnabled": True,
        "checkinEnabled": True,
        "pointsRedemptionEnabled": True,
        "referralEnabled": True,
        "leaderboardEnabled": False,
        "checkinBasePoints": 10,
        "checkinStreakBonusEvery": 7,
        "checkinStreakBonusPoints": 20,
        "pointsPerDay": 100,
        "maxRedeemDays": 30,
        "referralRewardPoints": 50,
        "referralInviteValidDays": 7,
        "referralAccountDays": 30,
        "referralMonthlyLimit": 3,
        "leaderboardLimit": 10,
        "expiryReminderDays": [7, 3, 1, 0],
    },
    "sections": {
        "benefits": [
            {"title": "声音内容库", "body": "把小说、播客、课程和收藏内容集中在一个干净入口里，随时打开，继续收听。"},
            {"title": "连续收听体验", "body": "支持进度记忆、章节浏览、倍速播放和跨设备接续，适合长期沉浸式收听。"},
            {"title": "稳定访问体验", "body": "通过受邀账号使用，减少公共入口干扰，让声音内容服务更安静、更可靠。"},
        ],
        "steps": [
            "领取邀请码或账号",
            "选择 EchoShelf 等兼容客户端",
            "添加管理员提供的服务地址",
            "登录后开始你的声音旅程",
        ],
        "faq": [
            {"q": "必须使用 EchoShelf 吗？", "a": "EchoShelf 是推荐客户端之一；如果管理员提供其他兼容客户端，也可以按教程使用。"},
            {"q": "账号到期怎么办？", "a": "在账号中心兑换续期码即可延长有效期，到期账号可在续期后恢复。"},
            {"q": "在哪里看收听进度？", "a": "登录账号中心后进入“收听记录”，可以查看近期作品进度摘要。"},
        ],
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def clean_settings(
    value: dict[str, Any], schema: dict[str, Any] = DEFAULT_PUBLIC_SETTINGS
) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, default in schema.items():
        if key not in value:
            continue
        candidate = value[key]
        if isinstance(default, dict) and isinstance(candidate, dict):
            cleaned[key] = clean_settings(candidate, default)
        else:
            cleaned[key] = candidate
    return cleaned


def get_public_settings(session: Session | None = None) -> dict[str, Any]:
    if session is None:
        return deepcopy(DEFAULT_PUBLIC_SETTINGS)
    setting = session.get(AppSetting, PUBLIC_SETTINGS_KEY)
    if not setting:
        return deepcopy(DEFAULT_PUBLIC_SETTINGS)
    try:
        stored = json.loads(setting.value_json)
    except json.JSONDecodeError:
        stored = {}
    merged = deep_merge(DEFAULT_PUBLIC_SETTINGS, clean_settings(stored))
    telegram = merged.get("telegram")
    if isinstance(telegram, dict):
        telegram.pop("inactivityWarningDays", None)
    return merged


def update_public_settings(
    session: Session,
    patch: dict[str, Any],
    *,
    audit_log: AuditLog | None = None,
) -> dict[str, Any]:
    current = get_public_settings(session)
    updated = deep_merge(current, clean_settings(patch))
    setting = session.get(AppSetting, PUBLIC_SETTINGS_KEY)
    payload = json.dumps(updated, ensure_ascii=False)
    if setting:
        setting.value_json = payload
        setting.updated_at = utcnow()
    else:
        setting = AppSetting(key=PUBLIC_SETTINGS_KEY, value_json=payload)
        session.add(setting)
    if audit_log is not None:
        session.add(audit_log)
    session.commit()
    return updated
