from contextlib import asynccontextmanager
import logging
import os
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.config import Settings
from app.db import create_db_and_tables, get_engine, get_session
from app.logging_config import configure_json_logging, request_id_context
from app.observability import observe_http_request, render_metrics, request_timer
from app.routers.admin_bootstrap import router as admin_bootstrap_router
from app.routers.admin_codes import router as admin_codes_router
from app.routers.admin_settings import router as admin_settings_router
from app.routers.admin_users import router as admin_users_router
from app.routers.auth import router as auth_router
from app.routers.library import router as library_router
from app.routers.internal_tg import router as internal_tg_router
from app.routers.me import router as me_router
from app.routers.public import router as public_router

configure_json_logging()
logger = logging.getLogger(__name__)
settings = Settings()
allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine = get_engine(settings.database_url)
    create_db_and_tables(engine)
    yield


app = FastAPI(title="MoYin.CC Portal API", version="0.1.0", lifespan=lifespan)


def _request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "")
    return candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else uuid4().hex


@app.middleware("http")
async def _request_observability_middleware(request: Request, call_next):
    request_id = _request_id(request)
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started_at = request_timer()
    status = 500
    route_path = "unmatched"
    response: Response | None = None
    try:
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:  # noqa: BLE001 - this is the final sanitized HTTP boundary
            logger.exception("unhandled_request_error")
            response = JSONResponse(
                {"detail": "Internal server error", "requestId": request_id},
                status_code=500,
            )
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        try:
            route = request.scope.get("route")
            if route is not None:
                route_path = getattr(route, "path", "unmatched")
            try:
                duration = observe_http_request(
                    method=request.method,
                    path=route_path,
                    status=status,
                    started_at=started_at,
                )
            except Exception:  # noqa: BLE001 - telemetry must never affect the response
                logger.exception("http_metrics_failed")
                duration = max(0.0, request_timer() - started_at)
            try:
                logger.info(
                    "http_request_completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "route": route_path,
                        "status": status,
                        "duration_ms": round(duration * 1000, 3),
                    },
                )
            except Exception:  # logging failure is intentionally non-fatal  # nosec B110
                pass
        finally:
            request_id_context.reset(token)


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


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request, session: Session = Depends(get_session)) -> Response:
    configured_token = os.getenv("METRICS_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if not configured_token or supplied != f"Bearer {configured_token}":
        return Response(status_code=404)
    content, content_type = render_metrics(session)
    return Response(content=content, headers={"Content-Type": content_type})


app.include_router(public_router, prefix="/api/public", tags=["public"])
app.include_router(auth_router)
app.include_router(admin_bootstrap_router)
app.include_router(admin_codes_router)
app.include_router(admin_settings_router)
app.include_router(admin_users_router)
app.include_router(me_router)
app.include_router(library_router)
app.include_router(internal_tg_router)
