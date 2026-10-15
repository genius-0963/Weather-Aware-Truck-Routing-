# Stage 1: Build frontend assets
FROM node:22-alpine AS frontend-builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.26.1 --activate

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json tsconfig.json ./
COPY artifacts/weather-routing/package.json ./artifacts/weather-routing/
COPY artifacts/weather-routing/tsconfig.json ./artifacts/weather-routing/
COPY artifacts/weather-routing/vite.config.ts ./artifacts/weather-routing/
COPY lib/ ./lib/
COPY scripts/ ./scripts/

RUN pnpm install --frozen-lockfile

COPY artifacts/weather-routing/ ./artifacts/weather-routing/

RUN pnpm run build

# Stage 2: Production Python runtime + Gunicorn + WhiteNoise
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DJANGO_DEBUG=false

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY artifacts/weather-routing/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY artifacts/weather-routing/backend/ ./backend/

# Copy built frontend from Stage 1 into the directory expected by Django settings
COPY --from=frontend-builder /app/artifacts/weather-routing/dist/public ./dist/public

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/v1/health || exit 1

CMD exec gunicorn --chdir backend config.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --threads 4 \
    --timeout 60
