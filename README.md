# CROWND

**From Followers to Real Results.** CROWND is a creator-commerce platform foundation for brands to publish performance campaigns, creators to apply and share trackable referrals, and teams to attribute verified orders and calculate transparent rewards.

> **Implementation status:** usable full-stack foundation with a working FastAPI/SQLAlchemy API, React dashboard, role-aware auth, campaign/application/referral/order/reward flows, and demo payment mode. This is not a claim of production readiness: gateway settlement, email verification, payouts, audit-grade financial operations, and several product modules still need implementation and security review. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Product surfaces

- Premium responsive marketing site and dashboard in `frontend/` (Vite, React, TypeScript, TanStack Query, Recharts, Lucide).
- Versioned REST API in `backend/` (FastAPI, SQLAlchemy 2, Pydantic settings, JWT).
- Relational models for users, creator/brand profiles, products, campaigns, applications, referrals/clicks, orders, pending rewards, payouts, and admin audit records.
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
```

Vite proxies `/api/v1` to `http://127.0.0.1:8000` on the server side; the browser uses relative API paths. For a separately deployed API, set `VITE_API_URL` to its HTTPS `/api/v1` base and configure API CORS. Open the Vite URL printed by the dev server. OpenAPI is at `/docs` and health is `/api/v1/health`.

**Local-only demo accounts** (created by `python seed.py`): `brand@crownd.local` and `creator@crownd.local`, both use `CrownDemo!2026`. They are not production credentials. The seed command is idempotent.

## Configuration

See `backend/.env.example`. `DATABASE_URL` defaults to local SQLite. For PostgreSQL, use `postgresql+psycopg://...`. `JWT_SECRET` must be a long random secret outside local development. `APP_ENV=development` and `PAYMENT_MODE=simulator` are explicitly local-only settings; the simulator is not a payment provider and must not be used in a deployed environment. No Razorpay/email/S3 credentials are currently integrated. Frontend `VITE_API_URL` is optional for same-origin proxy deployment.

## Development and verification

```bash
# backend
cd backend && .venv/bin/pytest -q
# schema changes
cd backend && .venv/bin/alembic revision --autogenerate -m "describe change" && .venv/bin/alembic upgrade head
# frontend
cd frontend && npm run lint && npm test && npm run build
```

API workflows: register / log in as a brand and creator; create a brand product and draft campaign; publish it; creator applies; brand accepts; a unique referral is created; create an order with referral code. To simulate a paid order locally, pass `simulate_payment: true` while `APP_ENV=development` and `PAYMENT_MODE=simulator`; the endpoint labels this mode explicitly. The simulated flow is not safe for real money.

## Docker Compose

`docker compose up --build` starts PostgreSQL, API and a static web container at `http://localhost:8080` (API docs at `http://localhost:8000/docs`). Override `JWT_SECRET`, `POSTGRES_PASSWORD`, `APP_ENV=production`, and `PAYMENT_MODE` before any network exposure. The Compose file is an operational baseline; production hardening, secrets management, TLS, object storage, and payment integration remain deployment work.

## Architecture and docs

- [Architecture](docs/architecture.md) · [Database schema](docs/database-schema.md) · [API reference](docs/api-documentation.md)
- [Development roadmap/status](docs/development-roadmap.md) · [Testing](docs/testing-guide.md) · [Deployment](docs/deployment-guide.md) · [Security](docs/security-guide.md)
- [Authentication](docs/authentication.md) · [Attribution](docs/referral-attribution.md) · [Reward rules](docs/reward-calculation.md)

## Important limitations

Current access tokens are browser localStorage bearer tokens (not HTTP-only refresh-cookie sessions); registration has no email verification or recovery flow. The payment simulator only models local success, with no Razorpay order/signature/webhook code. Reward lifecycle currently creates pending records, but scheduled eligibility, refund/reversal workflow, payouts execution, and complete ledger/settlement reconciliation are not built. Messaging, notification persistence, image uploads, disputes/risk review and full customer cart/checkout UX are future work. See the status checklist for exact coverage.
