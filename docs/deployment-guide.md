# Deployment guide

## Local containers

`docker compose up --build` starts PostgreSQL 16, FastAPI with reviewed Alembic upgrades, React static hosting/Nginx, and a local Mailpit SMTP sink. The SPA is on `http://localhost:8080`, API docs on `http://localhost:8000/docs`, and local inbox on `http://localhost:8025`. Mailpit is a local sink only; its messages are not sent to external recipients. Configure `JWT_SECRET`, `POSTGRES_PASSWORD`, exact local CORS/frontend origin and trusted proxy settings before sharing beyond a development workstation.

## Hosted deployment readiness

Authentication now has strong password hashing, short-lived server-checked access tokens, HttpOnly rotating refresh cookies, reset/verification tokens, per-client throttling, and fail-closed production setting checks. A hosted app still needs all of the following configuration and operational work:

- Frontend: deploy `frontend` on Vercel/static hosting; configure `VITE_API_URL` to the HTTPS versioned API URL or a same-origin reverse proxy.
- API: build `backend/Dockerfile`; set `APP_ENV=production`, a unique strong `JWT_SECRET`, `DATABASE_URL`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `COOKIE_SECURE=true`, optional `COOKIE_DOMAIN`, `COOKIE_SAMESITE=none` only if the API is on a different site (otherwise keep `lax`), exact `FRONTEND_BASE_URL`, `CORS_ORIGINS`, and `TRUSTED_PROXY_IPS` to real immediate proxy addresses. Never trust a user-supplied forwarded header.
- Database: managed PostgreSQL with TLS, least-privilege role, backups/restore tests; deploy with `alembic upgrade head`. `main.py` no longer auto-creates schema.
- Rate limits: use managed Redis via `RATE_LIMIT_STORAGE_URI`, configure availability/monitoring, and test multi-instance behavior. Production refuses in-memory limit storage.
- Email: set `EMAIL_MODE=smtp`, SMTP host/port, credentials where needed, `SMTP_STARTTLS=true`, and `EMAIL_FROM`. Confirm actual delivery, bounce handling and link origin; no provider account is included.
- Enable TLS, CSP, observability, error/metrics alerts, migration/rollback runbook, dependency scanning and security review. Auth logs avoid secrets/PII but still require retention controls.
- Payments/storage: Phase 3 supports only an in-process DEMO outcome (no money/provider) and manual COD collection attestation; online payment is disabled. No provider, object storage or production email vendor beyond configurable SMTP is provisioned. Any real provider requires a separate approved implementation, security review and verification of signatures/webhooks/refunds, ledger controls and payouts.

Never mistake DEMO records for genuine payment, deploy with demo seed, use SQLite on ephemeral disk, default credentials, wildcard CORS, development email, or default JWT secret. Current repo is not yet production-ready.
