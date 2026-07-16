from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.db import create_db_and_tables, get_engine
from app.routers.admin_bootstrap import router as admin_bootstrap_router
from app.routers.admin_codes import router as admin_codes_router
from app.routers.admin_settings import router as admin_settings_router
from app.routers.admin_users import router as admin_users_router
from app.routers.auth import router as auth_router
from app.routers.library import router as library_router
from app.routers.internal_tg import router as internal_tg_router
from app.routers.me import router as me_router
from app.routers.public import router as public_router

settings = Settings()
allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine = get_engine(settings.database_url)
    create_db_and_tables(engine)
    yield


app = FastAPI(title="MoYin.CC Portal API", version="0.1.0", lifespan=lifespan)


def _allowed_origin_values() -> set[str]:
    values = set(allowed_origins)
    values.add(settings.portal_public_url.rstrip("/"))
    return {value for value in values if value}


@app.middleware("http")
async def _csrf_middleware(request: Request, call_next):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)
    if request.url.path in {"/api/auth/login", "/api/auth/register", "/api/admin/bootstrap"}:
        return await call_next(request)

    has_cookie_session = bool(request.cookies.get(settings.session_cookie_name))
    if not has_cookie_session:
        return await call_next(request)

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    allowed = _allowed_origin_values()
    candidate = origin or (referer.split("/", 3)[:3] and "/".join(referer.split("/", 3)[:3]) if referer else "")
    if candidate and candidate.rstrip("/") in allowed:
        return await call_next(request)
    return JSONResponse({"detail": "CSRF check failed"}, status_code=403)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(public_router, prefix="/api/public", tags=["public"])
app.include_router(auth_router)
app.include_router(admin_bootstrap_router)
app.include_router(admin_codes_router)
app.include_router(admin_settings_router)
app.include_router(admin_users_router)
app.include_router(me_router)
app.include_router(library_router)
app.include_router(internal_tg_router)
