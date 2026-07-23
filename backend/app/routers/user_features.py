from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.auth_deps import get_current_claims, get_current_user_from_claims
from app.db import get_session
from app.models import Code, MediaRequest, PortalUser, ReferralInvite
from app.routers.auth import ensure_user_can_login, get_abs_client_factory
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
from app.services.media_requests import MediaRequestLimitError, create_open_media_request, transition_open_media_request
from app.services.telegram_admin import configured_admin_ids
from app.services.telegram_notifications import enqueue_notification

router = APIRouter(prefix="/api/me", tags=["me-features"])


class RedeemPointsRequest(BaseModel):
    days: int = Field(ge=1, le=365)
    idempotencyKey: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class LeaderboardOptInRequest(BaseModel):
    enabled: bool


class CreateMediaRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=1000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("title must not be blank")
        return clean


def _user(
    claims: dict[str, Any] = Depends(get_current_claims),
    session: Session = Depends(get_session),
) -> PortalUser:
    user = get_current_user_from_claims(claims, session)
    ensure_user_can_login(user, session)
    if user.role not in {"admin", "root"} and user.status != "active":
        raise HTTPException(status_code=403, detail="账号已到期，请先续期后再使用此功能。")
    return user


def _features(session: Session) -> dict[str, Any]:
    value = get_public_settings(session).get("telegram")
    return value if isinstance(value, dict) else {}


def _require_feature(session: Session, key: str) -> dict[str, Any]:
    features = _features(session)
    if features.get(key, True) is False:
        raise HTTPException(status_code=403, detail="该功能当前未开放。")
    return features


def _int_feature(features: dict[str, Any], key: str, default: int) -> int:
    value = features.get(key)
    return default if value is None else int(value)


def _serialize_request(item: MediaRequest) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "details": item.details,
        "status": item.status,
        "adminNote": item.admin_note,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("/rewards")
def reward_summary(
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return points_summary(session, user)


@router.post("/checkin")
def daily_checkin(
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    features = _require_feature(session, "checkinEnabled")
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
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    features = _require_feature(session, "pointsRedemptionEnabled")
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
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "leaderboardEnabled")
    return set_leaderboard_opt_in(session, user, payload.enabled)


@router.get("/referrals")
def referral_history(
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "referralEnabled")
    invites = session.exec(
        select(ReferralInvite)
        .where(ReferralInvite.inviter_user_id == user.id)
        .order_by(ReferralInvite.created_at.desc())
        .limit(20)
    ).all()
    return {
        "items": [
            {
                "id": invite.id,
                "code": code.code if (code := session.get(Code, invite.code_id)) else None,
                "expiresAt": invite.expires_at.isoformat(),
                "rewardPoints": invite.reward_points,
                "used": invite.used_by_user_id is not None,
                "settledAt": invite.settled_at.isoformat() if invite.settled_at else None,
                "createdAt": invite.created_at.isoformat(),
            }
            for invite in invites
        ]
    }


@router.post("/referrals")
def create_referral(
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    features = _require_feature(session, "referralEnabled")
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


@router.get("/requests")
def my_requests(
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "requestsEnabled")
    items = session.exec(
        select(MediaRequest)
        .where(MediaRequest.portal_user_id == user.id)
        .order_by(MediaRequest.created_at.desc())
        .limit(20)
    ).all()
    return {"items": [_serialize_request(item) for item in items]}


@router.post("/requests")
def create_request(
    payload: CreateMediaRequest,
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "requestsEnabled")
    try:
        item = create_open_media_request(
            session,
            portal_user_id=user.id,
            title=payload.title,
            details=payload.details,
        )
    except MediaRequestLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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


def _owned_request(session: Session, user: PortalUser, request_id: str) -> MediaRequest:
    item = session.exec(
        select(MediaRequest).where(
            MediaRequest.id == request_id,
            MediaRequest.portal_user_id == user.id,
        )
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="请求不存在。")
    return item


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    request_id: str,
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned_request(session, user, request_id)
    try:
        item = transition_open_media_request(session, request_id=item.id, status="cancelled")
    except MediaRequestLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(item)
    return {"item": _serialize_request(item)}


@router.delete("/requests/{request_id}")
def delete_request(
    request_id: str,
    user: PortalUser = Depends(_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned_request(session, user, request_id)
    if item.status in {"pending", "accepted"}:
        raise HTTPException(status_code=409, detail="请先撤销待处理请求，再执行删除。")
    session.delete(item)
    session.commit()
    return {"ok": True, "id": request_id}
