# Architecture

CROWND remains a modular-monolith foundation: a TypeScript/React SPA calls a versioned FastAPI REST API, which owns authentication, authorization and business rules. SQLAlchemy 2 maps a relational PostgreSQL (production target) or SQLite (local) schema. FastAPI OpenAPI is served at `/docs`. Vite proxies `/api/v1` to the local API; Nginx in Compose proxies the same path.

## Modules

- `backend/app/api/v1/auth.py`: separate auth router for account lifecycle, sessions, refresh, verification, recovery, logout and session-aware throttling.
- `backend/app/api/v1/routes.py`: existing product/campaign/application/referral/order/reward/analytics/admin route boundary (still consolidated and due to split in Phase 2).
- `backend/app/services/auth.py`, `security.py`: Argon2id/legacy rehash, HMAC-bound opaque refresh token, JWT session validation, one-use hashed actions, rate/origin policy.
- `backend/app/services/email.py`: explicit disabled-email provider and configurable SMTP adapter.
- `backend/app/services/rewards.py`: Decimal reward calculation service.
- `backend/app/models/entities.py`: mapped relational entities, including revocable auth sessions and one-use account tokens; Alembic migration owns deployed schema.
- `frontend/src/services/api.ts`: Axios auth client with access token in JS memory only, refresh-cookie session restoration, one refresh retry on 401, and session-expiration event.
- `frontend/src/components/AuthFlows.tsx`: login/registration/recovery/verification UI; `frontend/src/routes/access.ts` contains testable role page guards.

The schema and API are in a transition from initial single-file implementation; avoid converting to microservices or replacing the working product foundation. Roadmap Phase 2 splits business routes/services and centralizes resource policies. Creator matching remains deterministic weighted rules; no paid external AI API is required.

## Request flow

Browser -> relative `/api/v1/...` -> Vite/Nginx proxy -> FastAPI -> auth session and role/ownership checks -> SQLAlchemy transaction -> relational storage. Refresh cookie is HttpOnly; access bearer is short-lived and in-memory in the SPA. Payment settlement must only occur after provider signature/webhook verification; current local simulation is not settlement.
