# CROWND

**From Followers to Real Results.** CROWND is a creator-commerce platform foundation for brands to publish performance campaigns, creators to apply and share trackable referrals, and teams to attribute verified orders and calculate transparent rewards.

> **Implementation status:** usable full-stack foundation with a working FastAPI/SQLAlchemy API, React dashboard, role-aware auth, campaign/application/referral/order/reward flows, and demo payment mode. This is not a claim of production readiness: gateway settlement, real payout execution, audit-grade financial operations, and several product modules still need implementation/security review. Verification/recovery mail and notifications are implemented but require a configured worker/SMTP provider; external inbox delivery was not verified. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Product surfaces

- Premium responsive marketing site and dashboard in `frontend/` (Vite, React, TypeScript, TanStack Query, Recharts, Lucide).
- Versioned REST API in `backend/` (FastAPI, SQLAlchemy 2, Pydantic settings, JWT).
- Relational models for users, creator/brand profiles, products, campaigns, applications, referrals/clicks, orders, rewards/ledger and admin audit, plus recipient-scoped notifications/preferences and an encrypted SQL email outbox.
- Local SQLite by default; PostgreSQL through `DATABASE_URL` or Compose.
- Explainable creator matching and creator score fields; percentage/fixed reward calculation uses Decimal.

## Run locally

Requirements: Python 3.11+, Node 20+, npm.

```bash
# Terminal 1 — API
cd backend
python -m venv .venv
. .venv/bin/activate             # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env             # replace JWT_SECRET before any shared use
alembic upgrade head
python seed.py                    # optional local demo accounts and sample campaign
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — web app
cd frontend
npm install
npm run dev -- --host 0.0.0.0

# Terminal 3 — SQL-backed email worker (same backend environment/config)
cd backend
. .venv/bin/activate
python -m app.worker
```

Vite proxies `/api/v1` to `http://127.0.0.1:8000` on the server side; the browser uses relative API paths. For a separately deployed API, set `VITE_API_URL` to its HTTPS `/api/v1` base and configure API CORS. Open the Vite URL printed by the dev server. OpenAPI is at `/docs` and health is `/api/v1/health`.

**Local-only demo accounts** (created by `python seed.py`): `brand@crownd.example.com` and `creator@crownd.example.com`, both use `CrownDemo!2026`. They are not production credentials. The seed command is idempotent; seeded accounts are locally verified so the demo can log in.

New signups require email verification and do not receive a session immediately. For a safe local email inbox, `docker compose up --build` starts Mailpit at `http://localhost:8025`; Compose routes mail to that local-only sink. When running the API directly, run a local Mailpit instance and set `EMAIL_MODE=smtp`, `SMTP_HOST=127.0.0.1`, `SMTP_PORT=1025`, `SMTP_STARTTLS=false`, `FRONTEND_BASE_URL=http://localhost:5173`, and matching `CORS_ORIGINS` in `backend/.env`; run the separate worker in Terminal 3 using the same `JWT_SECRET` and database URL. Or leave `EMAIL_MODE=disabled` (the app explicitly does not send email; the worker marks queued messages suppressed and new accounts cannot verify/login until delivery is configured). Never point local development at real customer email without purpose. Outbox messages, including one-use account links, are encrypted at rest; rotate `JWT_SECRET` only after pending deliveries are drained or safely handled.

## Customer shop and checkout

- Browse the real catalog at `/shop`; product detail routes are `/products/{id}`. Search, category/brand/price/stock filters, sorting and pagination are API-backed.
- Sign in before adding to cart. Cart lines persist in the server database per account and are re-priced at every read/checkout. Guest carts and guest-to-account merging are not implemented.
- `/cart`, `/checkout`, `/orders`, and `/orders/{public_id}` provide customer cart, order placement and tracking. Checkout requires a shipping address and is idempotent; it derives item prices from the DB and reserves inventory in a transaction. Cancellation is allowed for pending/confirmed unpaid orders and releases stock.
- Creator links at `/r/{code}` preserve a signed attribution cookie for `ATTRIBUTION_DAYS`; eligible checkout orders retain the referral ID for downstream reward processing.
- Checkout offers **Demo payment** (backend-simulated only; no real money), **Cash on delivery** (confirmed but unpaid until an admin records collection after delivery), and disabled **Online payment — coming soon**. Demo transactions are clearly marked and excluded from genuine revenue and payout calculations. Failed demo attempts cancel the order and release stock. See [Payment options](docs/PAYMENT_OPTIONS.md).
- Shipping/tax is currently zero/free; coupon codes, saved addresses, automatic pending-order expiration, and refund/partial-refund workflows are not implemented. COD may be fulfilled while unpaid; treat it as collected only after an administrator records collection.

## Configuration

See `backend/.env.example`. `DATABASE_URL` defaults to local SQLite. For PostgreSQL, use `postgresql+psycopg://...`. `JWT_SECRET` must be a unique high-entropy value (32+ characters) outside local development. Demo payment is always a local in-process simulation, not a payment provider or financial transaction; Online payment is disabled. `RATE_LIMIT_STORAGE_URI` uses memory only for one-process local development; production startup requires shared Redis storage. Production also requires TLS SMTP (`EMAIL_MODE=smtp`), secure cookies, HTTPS frontend/CORS origins and explicit trusted reverse-proxy IPs. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `EMAIL_FROM`, `FRONTEND_BASE_URL`, `CORS_ORIGINS`, `TRUSTED_PROXY_IPS`, `COOKIE_DOMAIN` (optional), `COOKIE_SECURE`, and `COOKIE_SAMESITE` (use `none` only with Secure cookies when the API is truly cross-site). No Razorpay/S3 credentials are currently integrated. Frontend `VITE_API_URL` is optional for same-origin proxy deployment. Never put secrets in Vite variables.

## Development and verification

```bash
# backend
cd backend && .venv/bin/pytest -q
# schema changes
cd backend && .venv/bin/alembic revision --autogenerate -m "describe change" && .venv/bin/alembic upgrade head
# frontend
cd frontend && npm run lint && npm test && npm run build
```

API workflows: verify and log in as a customer; add products to the persistent cart; submit `POST /checkout` with `payment_method: "demo"` or `"cod"` and an idempotency key. The demo processor runs only in-process; an optional `X-Demo-Payment-Test-Failure: true` header forces a failure scenario outside production for tests. It cannot claim success and never contacts a provider. COD remains unpaid until an administrator confirms collection after delivery. Guest `POST /orders` has been retired with HTTP 410.

## Docker Compose

`docker compose up --build` starts PostgreSQL, API, the separate SQL notification worker, local Mailpit, and a static web container at `http://localhost:8080` (API docs at `http://localhost:8000/docs`). API and worker share the same `JWT_SECRET` to decrypt queued mail. Override `JWT_SECRET`, `POSTGRES_PASSWORD`, and `APP_ENV=production` before any network exposure. The Compose file is an operational baseline; production hardening, secrets management, TLS, object storage, and payment integration remain deployment work.

## Architecture and docs

- [Architecture](docs/architecture.md) · [Database schema](docs/database-schema.md) · [API reference](docs/api-documentation.md)
- [Verified phased roadmap](docs/DEVELOPMENT_ROADMAP.md) · [Prior roadmap](docs/development-roadmap.md) · [Testing](docs/testing-guide.md) · [Deployment](docs/deployment-guide.md) · [Security](docs/security-guide.md)
- [Authentication](docs/authentication.md) · [Attribution](docs/referral-attribution.md) · [Reward rules](docs/reward-calculation.md) · [Payment options](docs/PAYMENT_OPTIONS.md)
- [Phase 8 notifications audit](docs/PHASE_8_NOTIFICATIONS_AUDIT.md) · [Phase 8 implementation and operations](docs/PHASE_8_NOTIFICATIONS.md)

## Important limitations

Authentication is materially hardened but is not independently audited: access tokens are in-memory only and refresh is revocable/HttpOnly; MFA, device-session UI and a full credential-stuffing defense remain absent. Email workflows require both the SQL outbox worker and SMTP configuration (Compose uses local Mailpit; disabled mode truthfully suppresses delivery). The worker is at-least-once, supports one worker process per deployment, and its liveness is not measured. Demo payments only produce an explicitly marked local simulated outcome; the API makes no financial transaction and has no payment-provider/webhook code. Demo rewards are marked non-payable and excluded from payout/revenue totals. COD collection requires admin confirmation and is audit-recorded, but is still manually attested rather than provider-verified. Reward lifecycle scheduling, genuine refund/reversal workflow, payout execution and complete ledger/settlement reconciliation are not built. One-to-one conversations, image uploads, and real payment/payout/shipping integrations remain future work; Phase 7 admin disputes/risk review and Phase 8 notifications are implemented locally but not independently security- or production-audited. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and [the detailed roadmap](docs/DEVELOPMENT_ROADMAP.md).
