import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth_deps import require_admin
from app.db import get_session
from app.models import AuditLog, Code, CodeRedemption
from app.services.codes import generate_code

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateCodesRequest(BaseModel):
    type: Literal["register", "renew"] = "register"
    durationDays: int = Field(ge=0, le=3650)
    count: int = Field(default=1, gt=0, le=100)
    maxUses: int = Field(default=1, gt=0, le=10000)
    perUserMaxUses: int = Field(default=1, gt=0, le=10000)
    expiresAt: datetime | None = None
    designatedUsername: str | None = None
    note: str | None = None


class UpdateCodeStatusRequest(BaseModel):
    status: Literal["active", "disabled"]


def serialize_code(code: Code) -> dict[str, Any]:
    return {
        "id": code.id,
        "code": code.code,
        "type": code.type,
        "durationDays": code.duration_days,
        "maxUses": code.max_uses,
        "perUserMaxUses": code.per_user_max_uses,
        "usedCount": code.used_count,
        "status": code.status,
        "expiresAt": code.expires_at.isoformat() if code.expires_at else None,
        "designatedUsername": code.designated_username,
        "note": code.note,
        "createdAt": code.created_at.isoformat() if code.created_at else None,
    }


@router.post("/codes")
def create_codes(
    payload: CreateCodesRequest,
    session: Session = Depends(get_session),
    claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    codes = [
        generate_code(
            session,
            type=payload.type,
            duration_days=payload.durationDays,
            max_uses=payload.maxUses,
            per_user_max_uses=payload.perUserMaxUses,
            expires_at=payload.expiresAt,
            designated_username=payload.designatedUsername,
            note=payload.note,
            created_by=str(claims.get("sub") or "admin"),
            commit=False,
        )
        for _ in range(payload.count)
    ]
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action="admin.codes.create_batch",
            target_type="code_batch",
            detail_json=json.dumps(
                {
                    "type": payload.type,
                    "durationDays": payload.durationDays,
                    "count": len(codes),
                    "codeIds": [code.id for code in codes],
                },
                ensure_ascii=False,
            ),
        )
    )
    session.commit()
    for code in codes:
        session.refresh(code)
    return {"codes": [serialize_code(code) for code in codes]}


@router.get("/codes")
def list_codes(
    session: Session = Depends(get_session),
    _claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    codes = session.exec(select(Code).order_by(Code.created_at.desc())).all()
    return {"codes": [serialize_code(code) for code in codes]}


@router.patch("/codes/{code_id}")
def update_code_status(
    code_id: str,
    payload: UpdateCodeStatusRequest,
    session: Session = Depends(get_session),
    claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    code = session.get(Code, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code not found")
    if code.used_count >= code.max_uses and payload.status == "active":
        raise HTTPException(status_code=400, detail="Code has no remaining uses")
    code.status = payload.status
    session.add(code)
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action=f"admin.code.{payload.status}",
            target_type="code",
            target_id=code.id,
        )
    )
    session.commit()
    session.refresh(code)
    return {"code": serialize_code(code)}


@router.delete("/codes/{code_id}")
def delete_code(
    code_id: str,
    session: Session = Depends(get_session),
    claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    code = session.get(Code, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code not found")
    redemption = session.exec(
        select(CodeRedemption).where(CodeRedemption.code_id == code_id)
    ).first()
    if redemption is not None:
        raise HTTPException(status_code=409, detail="已使用卡密只能停用，不能删除核销历史。")
    session.delete(code)
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action="admin.code.delete_unused",
            target_type="code",
            target_id=code.id,
        )
    )
    session.commit()
    return {"ok": True, "id": code_id}
