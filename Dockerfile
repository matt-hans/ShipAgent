# syntax=docker/dockerfile:1

FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --prefer-offline --no-audit
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS python-builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .


FROM python:3.12-slim AS production

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 shipagent && \
    useradd --uid 1000 --gid shipagent --shell /bin/bash --create-home shipagent

WORKDIR /app

COPY --from=python-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=shipagent:shipagent src ./src
COPY --chown=shipagent:shipagent pyproject.toml ./
COPY --chown=shipagent:shipagent scripts ./scripts
COPY --chown=shipagent:shipagent docs ./docs
COPY --from=frontend-builder --chown=shipagent:shipagent /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/data /app/labels && \
    chown -R shipagent:shipagent /app

USER shipagent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////app/data/shipagent.db \
    UPS_LABELS_OUTPUT_DIR=/app/labels \
    SHIPAGENT_ALLOW_MULTI_WORKER=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
