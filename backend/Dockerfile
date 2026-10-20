# syntax=docker/dockerfile:1
# Build context: repository root (needs backend/, help/ and seed/).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    CREWAI_DISABLE_TELEMETRY=true \
    CREWAI_TRACING_ENABLED=false \
    OTEL_SDK_DISABLED=true \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app
WORKDIR /app

# uv is needed only to build the virtualenv; the runtime image copies the venv and does not ship uv.
FROM base AS deps
ARG INSTALL_EMBEDDINGS=true
RUN pip install --no-cache-dir uv==0.11.7
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_EMBEDDINGS" = "true" ]; then EXTRA="--extra embeddings"; else EXTRA=""; fi; \
    uv sync --frozen --no-dev $EXTRA

FROM deps AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra embeddings --group dev
COPY backend/ /app/
COPY help/ /help/
COPY seed/ /seed/
ENV HELP_DIR=/help SEED_DIR=/seed APP_PROFILE=test DATA_DIR=/tmp/data
CMD ["python", "-m", "pytest"]

FROM base AS runtime
COPY --from=deps /opt/venv /opt/venv
COPY backend/ /app/
COPY help/ /help/
COPY seed/ /seed/
ENV HELP_DIR=/help SEED_DIR=/seed DATA_DIR=/data
RUN mkdir -p /data /backups /home/app/.cache && chown -R app:app /data /backups /home/app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
