# ==============================================================================
# Stage 1: Build Next.js 14 Production Frontend
# ==============================================================================
FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ==============================================================================
# Stage 2: Unified Cloud Run Production Image (FastAPI + Next.js on 0.0.0.0:$PORT)
# ==============================================================================
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=8080 \
    TRIPSAGE_DB_PATH=/tmp/tripsage.db \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8000

# Copy Node.js runtime from builder stage so no external apt repositories are required
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

# Install FastAPI & Operations-Research Solver dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source and compiled Next.js production artifacts
COPY backend/ /app/backend/
COPY --from=frontend-builder /app/frontend/package.json /app/frontend/package.json
COPY --from=frontend-builder /app/frontend/next.config.mjs /app/frontend/next.config.mjs
COPY --from=frontend-builder /app/frontend/node_modules /app/frontend/node_modules
COPY --from=frontend-builder /app/frontend/.next /app/frontend/.next

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8080
CMD ["/app/docker-entrypoint.sh"]
