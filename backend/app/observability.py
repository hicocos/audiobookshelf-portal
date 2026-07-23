from __future__ import annotations

import logging
import math
import os
from time import perf_counter
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import ReconciliationJob
from app.worker_health import worker_health_status

logger = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "moyin_http_requests_total",
    "Portal API HTTP requests.",
    ("method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "moyin_http_request_duration_seconds",
    "Portal API HTTP request duration.",
    ("method", "path"),
)
DEPENDENCY_READY = Gauge(
    "moyin_dependency_ready",
    "Last observed dependency readiness (1 ready, 0 unavailable).",
    ("component",),
)
RECONCILIATION_BACKLOG = Gauge(
    "moyin_reconciliation_backlog",
    "Reconciliation jobs awaiting action, by status.",
    ("status",),
)
WORKER_LAG = Gauge(
    "moyin_worker_lag_seconds",
    "Seconds since the built-in scheduler last completed; NaN before first success.",
)
BUILD_INFO = Gauge(
    "moyin_build_info",
    "Build metadata for the running API.",
    ("version", "git_sha", "build_time"),
)

for _component in ("database", "audiobookshelf"):
    DEPENDENCY_READY.labels(component=_component).set(0)
for _status in ("pending", "retry", "failed"):
    RECONCILIATION_BACKLOG.labels(status=_status).set(0)
WORKER_LAG.set(math.nan)
BUILD_INFO.labels(
    version=os.getenv("BUILD_VERSION", "dev"),
    git_sha=os.getenv("BUILD_COMMIT", "unknown"),
    build_time=os.getenv("BUILD_DATE", "unknown"),
).set(1)


def request_timer() -> float:
    return perf_counter()


def observe_http_request(*, method: str, path: str, status: int, started_at: float) -> float:
    duration = max(0.0, perf_counter() - started_at)
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, path=path).observe(duration)
    return duration


def set_dependency_ready(component: str, ready: bool) -> None:
    DEPENDENCY_READY.labels(component=component).set(1 if ready else 0)


def refresh_operational_metrics(session: Session) -> None:
    counts = dict(
        session.exec(
            select(ReconciliationJob.status, func.count(ReconciliationJob.id)).group_by(
                ReconciliationJob.status
            )
        ).all()
    )
    for status in ("pending", "retry", "failed"):
        RECONCILIATION_BACKLOG.labels(status=status).set(counts.get(status, 0))

    health: dict[str, Any] = worker_health_status()
    lag = health.get("lagSeconds")
    WORKER_LAG.set(float(lag) if isinstance(lag, int | float) else math.nan)


def render_metrics(session: Session) -> tuple[bytes, str]:
    try:
        refresh_operational_metrics(session)
    except Exception:  # noqa: BLE001 - a failed collector must not hide process metrics
        logger.exception("Failed to refresh operational metrics", extra={"component": "metrics"})
    return generate_latest(), CONTENT_TYPE_LATEST
