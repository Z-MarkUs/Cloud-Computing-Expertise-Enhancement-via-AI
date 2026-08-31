# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=22-alpine
ARG PYTHON_VERSION=3.12-slim-bookworm
ARG UV_VERSION=0.8.17

FROM node:${NODE_VERSION} AS frontend-build

WORKDIR /workspace/frontend

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store && \
    pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv


FROM python:${PYTHON_VERSION} AS python-build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /uvx /bin/

WORKDIR /workspace

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra azure --no-install-project

COPY src/ ./src/
COPY data/ ./data/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra azure --no-editable


FROM python:${PYTHON_VERSION} AS runtime

ARG BUILD_DATE=unknown
ARG BUILD_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="StratusGuide" \
      org.opencontainers.image.description="Source-grounded cloud computing tutor with offline and Azure providers" \
      org.opencontainers.image.source="https://github.com/Z-MarkUs/Cloud-Computing-Expertise-Enhancement-via-AI" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CLOUD_TUTOR_ENVIRONMENT=production \
    CLOUD_TUTOR_HOST=0.0.0.0 \
    CLOUD_TUTOR_PORT=8000 \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    HOME=/home/app

RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app && \
    mkdir -p /app/frontend && \
    chown -R app:app /app /home/app

COPY --from=python-build /opt/venv /opt/venv
COPY --from=frontend-build --chown=app:app /workspace/frontend/dist /app/frontend/dist

WORKDIR /app
USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "cloud_tutor.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
