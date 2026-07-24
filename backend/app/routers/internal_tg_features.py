import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.db import get_session
from app.internal_auth import require_internal_bot
from app.models import AuditLog, MediaRequest, PortalUser
from app.routers.auth import ensure_user_can_login, get_abs_client_factory
from app.services.community import is_group_policy_applicable, report_group_membership
from app.services.referrals import ReferralError, create_referral_invite
from app.services.rewards import (
    RewardError,
    checkin,
    leaderboard,
    points_summary,
    redeem_points_for_days,
    set_leaderboard_opt_in,
)
from app.services.settings import get_public_settings
from app.services.media_requests import MediaRequestDuplicateError, MediaRequestLimitError, create_open_media_request, media_request_status_label
from app.services.telegram_admin import configured_admin_ids
from app.services.telegram_binding import get_user_by_telegram_id
from app.services.telegram_notifications import enqueue_notification

router = APIRouter(
    prefix="/api/internal/tg",
    tags=["internal-tg-features"],
    dependencies=[Depends(require_internal_bot)],
)


class TelegramRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)


class RedeemPointsRequest(TelegramRequest):
    days: int = Field(ge=1, le=365)
    idempotencyKey: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class LeaderboardOptInRequest(TelegramRequest):
    enabled: bool


class ReferralRequest(TelegramRequest):
    pass


class CreateMediaRequest(TelegramRequest):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=1000)
    confirmDifferentVersion: bool = False

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("title must not be blank")
        return clean


class MembershipReport(TelegramRequest):
    groupId: str = Field(min_length=1, max_length=128)
    isMember: bool


def _features(session: Session) -> dict[str, Any]:
    value = get_public_settings(session).get("telegram")
    return value if isinstance(value, dict) else {}


def _require_feature(session: Session, key: str) -> dict[str, Any]:
    features = _features(session)
    if features.get(key, True) is False:
        raise HTTPException(status_code=403, detail="telegram feature is disabled")
    return features


def _int_feature(features: dict[str, Any], key: str, default: int) -> int:
    value = features.get(key)
    return default if value is None else int(value)


def _bound_user(session: Session, telegram_id: str) -> PortalUser:
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="telegram account is not bound")
    ensure_user_can_login(user, session)
    if user.role not in {"admin", "root"} and user.status != "active":
        raise HTTPException(status_code=403, detail="账号已到期，请先续期后再使用此功能。")
    return user


@router.get("/rewards/{telegram_id}")
def reward_summary(telegram_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = _bound_user(session, telegram_id)
    return {"user": {"username": user.username}, **points_summary(session, user)}


@router.post("/checkin")
def daily_checkin(payload: TelegramRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    features = _require_feature(session, "checkinEnabled")
    user = _bound_user(session, payload.telegramId)
    return checkin(
        session,
        user,
        base_points=_int_feature(features, "checkinBasePoints", 10),
        bonus_every=_int_feature(features, "checkinStreakBonusEvery", 7),
        bonus_points=_int_feature(features, "checkinStreakBonusPoints", 20),
    )


@router.post("/points/redeem")
async def redeem_points(
    payload: RedeemPointsRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    features = _require_feature(session, "pointsRedemptionEnabled")
    user = _bound_user(session, payload.telegramId)
    try:
        return await redeem_points_for_days(
            session,
            user,
            days=payload.days,
            points_per_day=_int_feature(features, "pointsPerDay", 100),
            max_days=_int_feature(features, "maxRedeemDays", 30),
            abs_factory=abs_factory,
            idempotency_key=payload.idempotencyKey,
        )
    except RewardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/leaderboard")
def public_leaderboard(session: Session = Depends(get_session)) -> dict[str, Any]:
    features = _require_feature(session, "leaderboardEnabled")
    return {
        "entries": leaderboard(
            session,
            limit=_int_feature(features, "leaderboardLimit", 10),
        )
    }


@router.post("/leaderboard/opt-in")
def leaderboard_opt_in(
    payload: LeaderboardOptInRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "leaderboardEnabled")
    user = _bound_user(session, payload.telegramId)
    return set_leaderboard_opt_in(session, user, payload.enabled)


@router.post("/referral/invite")
def referral_invite(
    payload: ReferralRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    features = _require_feature(session, "referralEnabled")
    user = _bound_user(session, payload.telegramId)
    try:
        return create_referral_invite(
            session,
            user,
            valid_days=_int_feature(features, "referralInviteValidDays", 7),
            account_days=_int_feature(features, "referralAccountDays", 30),
            reward_points=_int_feature(features, "referralRewardPoints", 50),
            monthly_limit=_int_feature(features, "referralMonthlyLimit", 3),
        )
    except ReferralError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _serialize_request(item: MediaRequest) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "details": item.details,
        "status": item.status,
        "statusLabel": media_request_status_label(item.status),
        "adminNote": item.admin_note,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("/requests/{telegram_id}")
def my_media_requests(
    telegram_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "requestsEnabled")
    user = _bound_user(session, telegram_id)
    items = session.exec(
        select(MediaRequest)
        .where(MediaRequest.portal_user_id == user.id)
        .order_by(MediaRequest.created_at.desc())
        .limit(20)
    ).all()
    return {"items": [_serialize_request(item) for item in items]}


@router.post("/requests")
def create_media_request(
    payload: CreateMediaRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "requestsEnabled")
    user = _bound_user(session, payload.telegramId)
    try:
        item = create_open_media_request(
            session,
            portal_user_id=user.id,
            title=payload.title,
            details=payload.details,
            confirm_different_version=payload.confirmDifferentVersion,
        )
    except MediaRequestDuplicateError as exc:
        raise HTTPException(status_code=409, detail={
            "code": "duplicate_title", "message": str(exc),
            "existingRequestId": exc.existing.id, "existingStatus": exc.existing.status,
            "canConfirmDifferentVersion": True,
        }) from exc
    except MediaRequestLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="telegram.media_request.create",
            target_type="media_request",
            target_id=item.id,
            detail_json=json.dumps({"title": item.title}, ensure_ascii=False),
        )
    )
    session.commit()
    for telegram_id in configured_admin_ids():
        enqueue_notification(
            session,
            dedupe_key=f"media-request-admin:{item.id}:{telegram_id}",
            telegram_id=telegram_id,
            kind="media_request_admin",
            message=(
                "📮 收到新的有声书工单\n\n"
                f"工单编号：{item.id}\n"
                f"提交用户：{user.username}\n"
                f"作品名称：{item.title}\n"
                f"详细信息：\n{item.details or '未提供'}\n\n"
                "请使用下方按钮处理。"
            ),
        )
    return {"item": _serialize_request(item)}


@router.get("/community/config")
def community_config(session: Session = Depends(get_session)) -> dict[str, Any]:
    features = _features(session)
    return {
        "enabled": bool(features.get("groupMembershipEnabled")),
        "scope": str(features.get("groupPolicyScope") or "new_users_only"),
        "groupId": str(features.get("requiredGroupId") or ""),
        "inviteUrl": str(features.get("requiredGroupInviteUrl") or ""),
        "graceHours": int(features.get("groupGraceHours") or 72),
    }


@router.get("/community/eligibility/{telegram_id}")
def community_eligibility(
    telegram_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    features = _features(session)
    user = get_user_by_telegram_id(session, telegram_id)
    return {
        "bound": user is not None,
        "applicable": bool(user and is_group_policy_applicable(user, features)),
        "scope": "new_users_only",
    }


@router.post("/community/report")
async def membership_report(
    payload: MembershipReport,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    features = _features(session)
    configured_group = str(features.get("requiredGroupId") or "")
    if not features.get("groupMembershipEnabled") or not configured_group:
        return {"enabled": False}
    if payload.groupId != configured_group:
        raise HTTPException(status_code=400, detail="unexpected group id")
    user = get_user_by_telegram_id(session, payload.telegramId)
    if user is None:
        return {"enabled": True, "bound": False, "isMember": payload.isMember}
    if not is_group_policy_applicable(user, features):
        return {
            "enabled": True,
            "bound": True,
            "applicable": False,
            "isMember": payload.isMember,
            "status": "exempt",
        }
    membership = await report_group_membership(
        session,
        user,
        group_id=configured_group,
        is_member=payload.isMember,
        grace_hours=_int_feature(features, "groupGraceHours", 72),
        abs_factory=abs_factory,
    )
    return {
        "enabled": True,
        "bound": True,
        "isMember": payload.isMember,
        "status": membership.status,
        "graceExpiresAt": (
            membership.grace_expires_at.isoformat()
            if membership.grace_expires_at
            else None
        ),
    }
