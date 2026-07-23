# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc

FROM ${UV_IMAGE} AS uv-bin
FROM ${PYTHON_IMAGE} AS build-base

ARG BUILD_VERSION=dev
ARG BUILD_COMMIT=unknown
ARG BUILD_DATE=unknown
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

COPY --from=uv-bin /uv /uvx /bin/
COPY pyproject.toml uv.lock ./

FROM build-base AS production-deps
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM build-base AS phase4-lab
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra lab --no-editable \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser alembic ./alembic
USER appuser
CMD ["uv", "run", "--frozen", "--no-sync", "alembic", "upgrade", "head"]

FROM ${PYTHON_IMAGE} AS runtime
ARG BUILD_VERSION=dev
ARG BUILD_COMMIT=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="MoYin Portal API" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    BUILD_VERSION="${BUILD_VERSION}" \
    BUILD_COMMIT="${BUILD_COMMIT}" \
    BUILD_DATE="${BUILD_DATE}"
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /app /data
COPY --from=production-deps --chown=appuser:appuser /app/.venv ./.venv
COPY --chown=appuser:appuser app ./app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
