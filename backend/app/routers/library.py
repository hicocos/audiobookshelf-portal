from datetime import datetime, UTC
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth_deps import get_current_claims, require_admin
from app.db import get_session
from app.models import PortalUser
from app.routers.auth import ensure_user_can_login, get_abs_client_factory
from app.services.inactivity import latest_listen_at, should_disable_for_inactivity
from app.services.settings import get_public_settings

router = APIRouter(prefix="/api/library", tags=["library"])


def _ms_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _hours(seconds: Any) -> float:
    try:
        return round(float(seconds or 0) / 3600, 1)
    except (TypeError, ValueError):
        return 0.0


def _public_library(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name") or "未命名媒体库",
        "mediaType": item.get("mediaType") or item.get("type") or "book",
        "icon": item.get("icon"),
        "lastScan": _ms_to_iso(item.get("lastScan")),
    }

def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    metadata = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
    return {
        "id": item.get("id"),
        "libraryId": item.get("libraryId"),
        "title": metadata.get("title") or item.get("relPath") or item.get("path") or "未命名作品",
        "author": metadata.get("authorName") or "",
        "narrator": metadata.get("narratorName") or "",
        "durationHours": _hours(media.get("duration")),
        "numTracks": media.get("numTracks") or media.get("numAudioFiles") or 0,
        "addedAt": _ms_to_iso(item.get("addedAt")),
    }


def _progress_title(item: dict[str, Any], items_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    library_item_id = str(item.get("libraryItemId") or "")
    library_item = items_by_id.get(library_item_id, {})
    media = library_item.get("media") if isinstance(library_item.get("media"), dict) else {}
    metadata = media.get("metadata") if isinstance(media.get("metadata"), dict) else {}
    title = (
        item.get("title")
        or item.get("mediaTitle")
        or metadata.get("title")
        or library_item.get("relPath")
        or library_item.get("path")
        or "未命名作品"
    )
    author = item.get("author") or metadata.get("authorName") or ""
    narrator = item.get("narrator") or metadata.get("narratorName") or ""
    return {"title": str(title), "author": str(author or ""), "narrator": str(narrator or "")}


def _safe_item_url(base_url: str | None, library_item_id: Any) -> str | None:
    item_id = str(library_item_id or "").strip()
    if not item_id or len(item_id) > 256:
        return None
    try:
        parsed = urlsplit(str(base_url or "").strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    base_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}/item/{quote(item_id, safe='')}", "", ""))


def _public_progress(
    item: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]] | None = None,
    *,
    public_base_url: str | None = None,
) -> dict[str, Any]:
    title_info = _progress_title(item, items_by_id or {})
    return {
        "id": item.get("id"),
        "libraryItemId": item.get("libraryItemId"),
        "openUrl": _safe_item_url(public_base_url, item.get("libraryItemId")),
        "title": title_info["title"],
        "author": title_info["author"],
        "narrator": title_info["narrator"],
        "mediaItemType": item.get("mediaItemType") or "book",
        "progressPercent": round(float(item.get("progress") or 0) * 100, 1),
        "currentHours": _hours(item.get("currentTime")),
        "durationHours": _hours(item.get("duration")),
        "isFinished": bool(item.get("isFinished")),
        "lastUpdate": _ms_to_iso(item.get("lastUpdate")),
    }




def _permission_list(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _allowed_library_ids(upstream_user: dict[str, Any]) -> set[str] | None:
    permissions = upstream_user.get("permissions") if isinstance(upstream_user.get("permissions"), dict) else {}
    if permissions.get("accessAllLibraries") is True:
        return None
    for key in ("librariesAccessible", "libraryIds", "libraries"):
        values = _permission_list(permissions.get(key) or upstream_user.get(key))
        if values:
            return values
    return set()

def _safe_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail="媒体库数据暂时不可用，请稍后重试。")


@router.get("/summary")
async def my_library_summary(
    claims: dict[str, Any] = Depends(get_current_claims),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = session.get(PortalUser, claims.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    # Enforce the same login gate as the rest of the portal: disabled/deleted
    # accounts must not be able to read their library just because the JWT
    # cookie is still valid. Expired users are allowed through (read-only).
    ensure_user_can_login(user, session)

    try:
        async with abs_factory() as abs_client:
            all_libraries = await abs_client.list_libraries()
            if user.role in {"admin", "root"}:
                # Portal admins are local-only accounts whose placeholder
                # abs_user_id does not exist upstream. Use the owner of the
                # configured ABS admin token so the account-center summary can
                # still show real library counts and listening progress.
                upstream_user = await abs_client.get_current_user()
            else:
                upstream_user = await abs_client.get_user(user.abs_user_id) if user.abs_user_id else {}
            progress = upstream_user.get("mediaProgress", []) if isinstance(upstream_user, dict) else []
            allowed_ids = _allowed_library_ids(upstream_user if isinstance(upstream_user, dict) else {})
            libraries = all_libraries if allowed_ids is None else [
                item for item in all_libraries if str(item.get("id") or "") in allowed_ids
            ]
            visible_ids = {str(item.get("id") or "") for item in libraries}
            progress_list = progress if isinstance(progress, list) else []
            recent = sorted(progress_list, key=lambda x: x.get("lastUpdate") or 0, reverse=True)[:5]
            progress_items: list[dict[str, Any]] = []
            for progress_entry in recent:
                item_id = str(progress_entry.get("libraryItemId") or "")
                if not item_id:
                    continue
                try:
                    progress_items.append(await abs_client.get_library_item(item_id))
                except (httpx.HTTPError, TypeError, RuntimeError):
                    # One removed/corrupt library item must not hide the rest of
                    # the user's listening summary. Its card will keep the
                    # existing fallback title while resolvable items stay named.
                    continue
            sample_items: list[dict[str, Any]] = []
            for library in libraries[:3]:
                library_id = library.get("id")
                if library_id:
                    sample_items.extend(await abs_client.list_library_items(str(library_id), limit=8))
            sample_items = [item for item in sample_items if str(item.get("libraryId") or "") in visible_ids or allowed_ids is None]
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise _safe_error(exc) from exc

    items_by_id = {
        str(item.get("id")): item
        for item in [*sample_items, *progress_items]
        if item.get("id")
    }
    return {
        "libraries": [_public_library(item) for item in libraries],
        "items": [_public_item(item) for item in sample_items],
        "progress": [
            _public_progress(
                item,
                items_by_id,
                public_base_url=str(
                    get_public_settings(session).get("client", {}).get("serverUrl") or ""
                ),
            )
            for item in recent
        ],
        "stats": {
            "libraryCount": len(libraries),
            "itemPreviewCount": len(sample_items),
            "progressCount": len(progress_list),
        },
    }


@router.get("/admin/overview")
async def admin_library_overview(
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    try:
        async with abs_factory() as abs_client:
            libraries = await abs_client.list_libraries()
            users = await abs_client.list_users()
            user_details_by_id: dict[str, dict[str, Any]] = {}
            for item in users:
                user_id = str(item.get("id") or "")
                progress = item.get("mediaProgress")
                progress = progress if isinstance(progress, list) else None
                if (progress is None or not progress) and user_id:
                    try:
                        user_details_by_id[user_id] = await abs_client.get_user(user_id)
                    except (httpx.HTTPError, TypeError, RuntimeError):
                        user_details_by_id[user_id] = item
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise _safe_error(exc) from exc

    public_users = []
    total_progress = 0
    portal_users = session.exec(select(PortalUser)).all()
    portal_by_abs_id = {str(user.abs_user_id): user for user in portal_users if user.abs_user_id}
    settings = get_public_settings(session)
    operations = settings.get("operations")
    operations = operations if isinstance(operations, dict) else {}
    inactive_days = int(operations.get("inactiveDays") or 30)
    grace_days = int(operations.get("newUserGraceDays") or 7)
    inactive_candidates = 0
    for item in users:
        user_id = str(item.get("id") or "")
        detail = user_details_by_id.get(user_id, item)
        progress = item.get("mediaProgress")
        progress = progress if isinstance(progress, list) else []
        detail_progress = detail.get("mediaProgress")
        if isinstance(detail_progress, list) and detail_progress:
            progress = detail_progress
        total_progress += len(progress)
        merged_item = {**item, **detail, "mediaProgress": progress}
        portal_user = portal_by_abs_id.get(user_id)
        latest = latest_listen_at(merged_item)
        should_disable = False
        inactivity_reason = "未绑定门户账号"
        if portal_user is not None:
            should_disable, inactivity_reason = should_disable_for_inactivity(
                portal_user,
                merged_item,
                inactive_days=inactive_days,
                new_user_grace_days=grace_days,
            )
            inactive_candidates += int(should_disable)
        public_users.append(
            {
                "id": merged_item.get("id"),
                "username": merged_item.get("username"),
                "type": merged_item.get("type"),
                "isActive": merged_item.get("isActive"),
                "lastSeen": _ms_to_iso(merged_item.get("lastSeen")),
                "latestListenAt": latest.isoformat() if latest else None,
                "progressCount": len(progress),
                "portalUserId": portal_user.id if portal_user else None,
                "portalStatus": portal_user.status if portal_user else None,
                "portalCreatedAt": (
                    portal_user.created_at.isoformat() if portal_user else None
                ),
                "inactivityCandidate": should_disable,
                "inactivityReason": inactivity_reason,
            }
        )
    return {
        "libraries": [_public_library(item) for item in libraries],
        "users": public_users,
        "stats": {
            "libraryCount": len(libraries),
            "upstreamUserCount": len(users),
            "activeUserCount": sum(1 for item in users if item.get("isActive") is True),
            "progressCount": total_progress,
            "portalUserCount": len(portal_users),
            "inactiveCandidateCount": inactive_candidates,
        },
    }


@router.get("/admin/libraries")
async def admin_list_libraries(
    _claims: dict[str, Any] = Depends(require_admin),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    try:
        async with abs_factory() as abs_client:
            libraries = await abs_client.list_libraries()
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise _safe_error(exc) from exc
    return {"libraries": [_public_library(item) for item in libraries]}


@router.get("/admin/libraries/{library_id}/items")
async def admin_list_library_items(
    library_id: str,
    limit: int = 50,
    _claims: dict[str, Any] = Depends(require_admin),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    try:
        async with abs_factory() as abs_client:
            items = await abs_client.list_library_items(library_id, limit=safe_limit)
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise _safe_error(exc) from exc
    public_items = [_public_item(item) for item in items]
    return {
        "libraryId": library_id,
        "items": public_items,
        "count": len(public_items),
        "limit": safe_limit,
    }
