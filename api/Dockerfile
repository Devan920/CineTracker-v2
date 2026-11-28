# =============================================================================
# Stage 1: Builder (Python wheels + Playwright Chromium binary cache)
# =============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY api/requirements.txt /build/api/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /build/api/requirements.txt \
    && mkdir -p /ms-playwright \
    && python -m playwright install chromium

# =============================================================================
# Stage 2: Hardened Non-Root Production Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/scraper \
    PATH="/opt/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/appuser

WORKDIR /app

# Install runtime dependencies needed by curl healthcheck & headless Chromium
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /ms-playwright /ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged runtime user & group
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser

COPY --chown=appuser:appuser scraper /app/scraper
COPY --chown=appuser:appuser api /app/api

RUN mkdir -p /app/scraper/logs /app/scraper/cache \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
