# syntax=docker/dockerfile:1

FROM node:20.19-alpine AS frontend-builder

WORKDIR /app/shipagent-frontend
COPY shipagent-frontend/package.json shipagent-frontend/package-lock.json ./
RUN npm ci --prefer-offline --no-audit
COPY shipagent-frontend/ ./
# NODE_OPTIONS preload avoids an intermittent Node require(esm) race in the
# Angular build (see scripts/preload-compiler-cli.cjs); NX_DAEMON=false avoids a
# stale daemon, NX_NO_CLOUD=true skips unauthenticated Nx Cloud calls.
RUN NODE_OPTIONS="--require /app/shipagent-frontend/scripts/preload-compiler-cli.cjs" \
    NX_DAEMON=false NX_NO_CLOUD=true \
    npx nx run-many -t build --configuration=production && ./scripts/link-remotes.sh


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
COPY --from=frontend-builder --chown=shipagent:shipagent /app/shipagent-frontend/dist/apps/shell/browser ./shipagent-frontend/dist/apps/shell/browser

RUN mkdir -p /app/data /app/labels && \
    chown -R shipagent:shipagent /app

USER shipagent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////app/data/shipagent.db \
    UPS_LABELS_OUTPUT_DIR=/app/labels \
    SHIPAGENT_ALLOW_MULTI_WORKER=false \
    SHIPAGENT_PORT=8080

EXPOSE ${SHIPAGENT_PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${SHIPAGENT_PORT}/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec python -m src.bundle_entry serve --host 0.0.0.0 --port ${SHIPAGENT_PORT}"]
