# FastAPI image for the production API.
#
# Provider integrations use external services, so the image stays CPU-only and
# does not bundle local Ollama models or other model runtimes.
FROM python:3.11-slim

# Pillow and psycopg[binary] publish wheels for this image. curl is required
# only by the container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Keep dependency installation cached when only application code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Production releases run Alembic before the new application starts.
COPY alembic.ini .
COPY migrations ./migrations

# Run the service without root privileges. Local asset directories remain
# writable for development-like configurations, although production uses R2.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/asset_cache /app/audio_cache \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

# Run one process per machine; horizontal scaling provides additional workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
