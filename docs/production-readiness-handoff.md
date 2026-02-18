# ShipAgent Production Readiness Handoff (Local Docker)

Date: 2026-02-18

This handoff captures the current, code-verified deployment contract for local Docker deployment.

## Verified Corrections

1. Database configuration is `DATABASE_URL` (canonical). `SHIPAGENT_DB_PATH` is supported as compatibility fallback.
2. `FILTER_TOKEN_SECRET` is required at startup and must be set in `.env`.
3. Conversation runtime has shutdown cleanup; preview-triggered background batch tasks are now drained/cancelled on shutdown.
4. `CONVERSATION_TASK_QUEUE_MODE` remains informational in current code (no external queue backend implemented).
5. Local ops scripts exist and are runnable:
   - `/app/scripts/backup.sh`
   - `/app/scripts/restore.sh`
   - host wrapper: `./scripts/shipagent`

## Local Deployment Contract

1. Build and run:
   ```bash
   cp .env.example .env
   docker compose up -d --build
   ```
2. UI:
   - `http://localhost:8000`
3. CLI:
   ```bash
   ./scripts/shipagent version
   ./scripts/shipagent job list
   ```
4. Health:
   - Liveness: `GET /health`
   - Readiness: `GET /readyz`

## Security Defaults (Local)

1. API auth is optional and disabled by default.
2. Set `SHIPAGENT_API_KEY` to enforce `X-API-Key` on `/api/*`.
3. CORS is env-driven via `ALLOWED_ORIGINS` (unset = same-origin only).

