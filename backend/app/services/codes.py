import secrets
from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import Session, select

from app.models import Code, CodeRedemption


class CodeValidationError(ValueError):
    pass


def _new_code() -> str:
    # Human-ish groups while keeping enough entropy for invite codes.
    raw = secrets.token_urlsafe(9).replace("_", "").replace("-", "").upper()
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


def generate_code(
    session: Session,
    *,
    type: str,
    duration_days: int,
    created_by: str | None = None,
    max_uses: int = 1,
    expires_at: datetime | None = None,
    designated_username: str | None = None,
    note: str | None = None,
) -> Code:
    for _ in range(10):
        value = _new_code()
        exists = session.exec(select(Code).where(Code.code == value)).first()
        if not exists:
            code = Code(
                code=value,
                type=type,
                duration_days=duration_days,
                max_uses=max_uses,
                expires_at=expires_at,
                designated_username=designated_username,
                created_by=created_by,
                note=note,
            )
            session.add(code)
            session.commit()
            session.refresh(code)
            return code
    raise RuntimeError("Failed to generate unique code")


# Maps the redemption action to the code type that is allowed to perform it.
# Registration may only consume invite ("register") codes; renewal may only
# consume "renew" codes. This enforcement happens BEFORE the code is consumed,
# so a wrong-purpose code is never burned on a rejected request.
_ACTION_TO_TYPE = {
    "register": "register",
    "renew": "renew",
}


def validate_code(session: Session, code_value: str, *, username: str | None = None, action: str) -> Code:
    normalized = code_value.strip().upper()
    code = session.exec(select(Code).where(Code.code == normalized)).first()
    if code is None:
        raise CodeValidationError("code not found")
    if code.status != "active":
        raise CodeValidationError("code is not active")
    now = datetime.now(UTC)
    expires_at = code.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at is not None and expires_at <= now:
        raise CodeValidationError("code expired")
    if code.used_count >= code.max_uses:
        raise CodeValidationError("code already used")
    if username is not None and code.designated_username and code.designated_username.lower() != username.lower():
        raise CodeValidationError("code designated for another username")

    # Enforce purpose: invite codes register, renew codes renew. Checked before
    # consuming so a mismatched code is rejected without spending a use.
    expected_type = _ACTION_TO_TYPE.get(action)
    if expected_type is not None and code.type != expected_type:
        if action == "register":
            raise CodeValidationError("code is not an invite code")
        raise CodeValidationError("code is not a renewal code")
    return code


def redeem_code(session: Session, code_value: str, *, username: str, action: str, commit: bool = True) -> Code:
    code = validate_code(session, code_value, username=username, action=action)

    result = session.exec(
        update(Code)
        .where(
            Code.id == code.id,
            Code.status == "active",
            Code.used_count < Code.max_uses,
        )
        .values(used_count=Code.used_count + 1)
    )
    if result.rowcount != 1:
        raise CodeValidationError("code already used")
    session.refresh(code)
    redemption = CodeRedemption(
        code_id=code.id,
        username_snapshot=username,
        action=action,
    )
    session.add(redemption)
    if commit:
        session.commit()
        session.refresh(code)
    return code
