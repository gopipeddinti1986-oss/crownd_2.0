# Deployment guide

## Local containers

Copy the root `.env.example` to `.env`, replace local placeholders, then run `docker compose up --build`. This starts PostgreSQL 16, a one-shot Alembic migration service, API, separate SQL notification worker, and Nginx SPA at `http://localhost:8080`; API routes are same-origin under `/api/v1` and the API/docs ports are not published directly. Compose defaults to disabled email. To add the local-only Mailpit inbox on `http://localhost:8025`, enable the `dev-mail` profile and explicitly set the local Mailpit SMTP values described in the root `.env.example`. Mailpit messages are not delivered externally. Compose is for local development, not production. See the [Phase 10 deployment guide](PHASE_10_DEPLOYMENT_GUIDE.md), [audit](PHASE_10_DEPLOYMENT_AUDIT.md), [backup/recovery runbook](DATABASE_BACKUP_AND_RECOVERY.md), and [production readiness checklist](PRODUCTION_READINESS_CHECKLIST.md).

## Hosted deployment readiness

Authentication now has strong password hashing, short-lived server-checked access tokens, HttpOnly rotating refresh cookies, reset/verification tokens, per-client throttling, and fail-closed production setting checks. A hosted app still needs all of the following configuration and operational work:

- Frontend: deploy `frontend` on Vercel/static hosting; configure `VITE_API_URL` to the HTTPS versioned API URL or a same-origin reverse proxy.
- API: build `backend/Dockerfile`; set `APP_ENV=production`, a unique strong `JWT_SECRET`, `DATABASE_URL`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `COOKIE_SECURE=true`, optional `COOKIE_DOMAIN`, `COOKIE_SAMESITE=none` only if the API is on a different site (otherwise keep `lax`), exact `FRONTEND_BASE_URL`, `CORS_ORIGINS`, and `TRUSTED_PROXY_IPS` to real immediate proxy addresses. Never trust a user-supplied forwarded header.
- Notification worker: run one dedicated `python -m app.worker` process with the same database URL, `JWT_SECRET`, and SMTP configuration as the API. It polls the SQL outbox, retries up to five times and records static error codes; SMTP acceptance is not proof of inbox delivery. Worker liveness is not currently measured and multi-process contention has not been stress-tested.
- Database: managed PostgreSQL with TLS, least-privilege role, backups/restore tests; deploy with `alembic upgrade head`. `main.py` no longer auto-creates schema.
- Rate limits: use managed Redis via `RATE_LIMIT_STORAGE_URI`, configure availability/monitoring, and test multi-instance behavior. Production refuses in-memory limit storage.
- Email: set `EMAIL_MODE=smtp`, SMTP host/port, credentials where needed, `SMTP_STARTTLS=true`, and `EMAIL_FROM`; run the worker. Existing verification/reset links are encrypted in the outbox using a key derived from `JWT_SECRET`, so drain/handle queued rows before rotating that secret. Confirm actual delivery, bounce handling and link origin; no provider account is included.
- Enable TLS, CSP, observability, error/metrics alerts, migration/rollback runbook, dependency scanning and security review. Auth logs avoid secrets/PII but still require retention controls.
- Payments/storage: Phase 3 supports only an in-process DEMO outcome (no money/provider) and manual COD collection attestation; online payment is disabled. No provider, object storage or production email vendor beyond configurable SMTP is provisioned. Any real provider requires a separate approved implementation, security review and verification of signatures/webhooks/refunds, ledger controls and payouts.

Never mistake DEMO records for genuine payment, deploy with demo seed, use SQLite on ephemeral disk, default credentials, wildcard CORS, development email, or default JWT secret. Current repo is not yet production-ready.
