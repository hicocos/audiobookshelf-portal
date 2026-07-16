from fastapi import Response

from app.config import Settings


def set_session_cookie(response: Response, token: str, settings: Settings | None = None) -> None:
    settings = settings or Settings()
    max_age = int(settings.access_token_expire_minutes) * 60
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings | None = None) -> None:
    settings = settings or Settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=bool(settings.session_cookie_secure),
        samesite=settings.session_cookie_samesite,
        httponly=True,
    )
