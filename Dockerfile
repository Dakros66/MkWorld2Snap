FROM node:22-alpine AS ui_assets

WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

FROM python:3.12-slim AS app_runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY profiles/ ./profiles/
COPY backend/ ./backend/
COPY --from=ui_assets /build/frontend/dist ./frontend/dist

RUN mkdir -p \
    /app/target_profiles \
    /app/outputs \
    /app/rules \
    /app/tmp \
    /app/user_profiles

ENV PYTHONPATH=/app/backend \
    MKWORLD2SNAP_APP_ROOT=/app \
    MKWORLD2SNAP_TARGET_PROFILES=/app/target_profiles \
    MKWORLD2SNAP_FRONTEND_DIST=/app/frontend/dist \
    MKWORLD2SNAP_PROFILES=/app/profiles \
    MKWORLD2SNAP_RULES=/app/rules \
    MKWORLD2SNAP_TMP=/app/tmp \
    MKWORLD2SNAP_USER_PROFILES=/app/user_profiles \
    CLEANUP_TEMP_AFTER_SECONDS=300 \
    MAX_UPLOAD_MB=500 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 mkworld \
    && chown -R mkworld:mkworld /app

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "backend.local_gateway:app", "--host=0.0.0.0", "--port=8080", "--workers=1"]
