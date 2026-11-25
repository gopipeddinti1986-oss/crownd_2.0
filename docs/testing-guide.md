# Testing guide

Backend tests use pytest + an isolated in-memory SQLite database and FastAPI TestClient. Run from `backend/`: `.venv/bin/pytest -q`. Auth coverage includes registration without auto-login, Argon2id and legacy rehash, invalid credentials, email verification and expiry/replay, token expiration, cookie flags, refresh rotation/replay/forged-token containment, logout/logout-all, reset token expiry/replay/session invalidation, authorization and resource ownership, origin checks, rate limiting, production config fail-closed, and disabled-email behavior. Product regression tests cover campaign application/referral/order/reward and Decimal math.

Frontend: `cd frontend && npm run lint && npm test && npm run build`. Unit tests cover access-token memory-only storage, cookie-based restoration, role page guards, and INR/reward calculations. API integration with a full browser is not an E2E claim: there is no Playwright suite yet.

Run `alembic upgrade head` against a disposable SQLite DB and against a copy/backup of an existing DB before release. Deployment verification must additionally cover Postgres migration rollback, Redis-backed distributed rate limits, SMTP TLS/mail sink, trusted-proxy/origin behavior, concurrency, SQL query scope, payments and payout flows. The payment provider flows do not exist and are not testable as live payments.
