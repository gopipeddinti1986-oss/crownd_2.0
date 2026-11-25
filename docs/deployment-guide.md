# Deployment guide

## Local containers

`docker compose up --build` uses Postgres 16, FastAPI, migrations and Nginx static SPA. The web container serves on port 8080; API docs on port 8000. Override local defaults before use; do not publish container ports without TLS/network policy.

## Hosted deployment outline (not yet completed)

- Frontend: deploy `frontend` on Vercel or static hosting, set `VITE_API_URL` to the HTTPS versioned API URL (or configure same-origin reverse proxy).
- API: build `backend/Dockerfile` on a Python container host; configure `DATABASE_URL`, high-entropy `JWT_SECRET`, `APP_ENV=production`, `PAYMENT_MODE` only after real gateway support, and exact production `CORS_ORIGINS`.
- Database: managed PostgreSQL with SSL, backups, least-privilege application role, reviewed Alembic migration.
- Storage/email/payments: no production adapter is implemented. Configure these only after their respective integration and verification work.
- Enable TLS, health checks, structured logs, error/metrics alerts, backups, migration rollback plan, dependency scanning and security review.

Never deploy with local simulator, demo users, SQLite on ephemeral disk, default credentials, wildcard CORS, or default JWT secret. This repository is not production ready yet.
