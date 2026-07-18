from typing import Any

from app.models import PortalUser


FEATURE_REASON = {
    "renewalEnabled": "续期功能当前未开放。",
    "checkinEnabled": "签到功能当前未开放。",
    "pointsRedemptionEnabled": "积分兑换功能当前未开放。",
    "referralEnabled": "好友邀请功能当前未开放。",
    "requestsEnabled": "内容请求功能当前未开放。",
    "leaderboardEnabled": "排行榜功能当前未开放。",
}

EXPIRED_REASON = {
    "listen": "账号已到期，请先续期恢复收听。",
    "checkin": "账号已到期，请先续期后再签到。",
    "redeemPoints": "账号已到期，请先续期后再使用积分。",
    "refer": "账号已到期，请先续期后再邀请好友。",
    "request": "账号已到期，请先续期后再提交内容请求。",
    "leaderboard": "账号已到期，请先续期后再查看排行榜。",
}


def user_capabilities(user: PortalUser, settings: dict[str, Any]) -> dict[str, Any]:
    """Return the single user-facing capability contract shared by Web and Bot clients."""
    telegram = settings.get("telegram")
    features = telegram if isinstance(telegram, dict) else {}
    privileged = user.role in {"admin", "root"}
    active = user.status == "active" or privileged

    def enabled(key: str) -> bool:
        return features.get(key, True) is not False

    capabilities: dict[str, Any] = {
        "canListen": active,
        "canRenew": enabled("renewalEnabled"),
        "canChangePassword": user.status in {"active", "expired"} or privileged,
        "canCheckin": active and enabled("checkinEnabled"),
        "canRedeemPoints": active and enabled("pointsRedemptionEnabled"),
        "canRefer": active and enabled("referralEnabled"),
        "canRequest": active and enabled("requestsEnabled"),
        "canViewLeaderboard": active and enabled("leaderboardEnabled"),
        "canAdmin": privileged and user.status == "active",
    }

    reasons: dict[str, str] = {}
    if not capabilities["canListen"]:
        reasons["listen"] = EXPIRED_REASON["listen"] if user.status == "expired" else "账号当前不可收听，请联系管理员。"

    checks = (
        ("canRenew", "renew", "renewalEnabled"),
        ("canCheckin", "checkin", "checkinEnabled"),
        ("canRedeemPoints", "redeemPoints", "pointsRedemptionEnabled"),
        ("canRefer", "refer", "referralEnabled"),
        ("canRequest", "request", "requestsEnabled"),
        ("canViewLeaderboard", "leaderboard", "leaderboardEnabled"),
    )
    for capability, reason_key, feature_key in checks:
        if capabilities[capability]:
            continue
        if not enabled(feature_key):
            reasons[reason_key] = FEATURE_REASON[feature_key]
        elif user.status == "expired" and reason_key in EXPIRED_REASON:
            reasons[reason_key] = EXPIRED_REASON[reason_key]
        else:
            reasons[reason_key] = "当前账号不能使用此功能。"

    if not capabilities["canChangePassword"]:
        reasons["changePassword"] = "当前账号不能修改密码，请联系管理员。"
    if not capabilities["canAdmin"] and user.status != "active":
        reasons["admin"] = "当前账号没有管理权限。"

    capabilities["unavailableReasons"] = reasons
    return capabilities
