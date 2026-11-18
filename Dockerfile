# syntax=docker/dockerfile:1
# Stage 1: Dependency Builder
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# Stage 2: Hardened Non-Root Runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PULSEFLOW_ENV=development \
    PULSEFLOW_HOST=0.0.0.0 \
    PULSEFLOW_PORT=8095 \
    PULSEFLOW_SQLITE_PATH=/app/data/pulseflow.db

RUN groupadd --gid 10001 pulseflow && \
    useradd --uid 10001 --gid pulseflow --shell /bin/bash --create-home pulseflow && \
    mkdir -p /app/data && \
    chown -R pulseflow:pulseflow /app

WORKDIR /app

COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* && \
    rm -rf /wheels

COPY --chown=pulseflow:pulseflow src ./src
COPY --chown=pulseflow:pulseflow ui ./ui
COPY --chown=pulseflow:pulseflow migrations ./migrations

USER pulseflow

EXPOSE 8095

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/api/v1/health', timeout=3)" || exit 1

CMD ["python", "-m", "src.interfaces.http.server"]
