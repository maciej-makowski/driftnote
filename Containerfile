# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

# uv is the dependency installer
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# System deps: HEIC decoding (libheif), video poster (ffmpeg), tzdata
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libheif1 \
        ffmpeg \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY config /app/config

RUN useradd --system --create-home --uid 1000 driftnote \
    && mkdir -p /var/driftnote/data /var/driftnote/backups \
    && chown -R driftnote:driftnote /var/driftnote /app

USER driftnote

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "--factory", "driftnote.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
