# Architecture

CROWND remains a modular-monolith foundation: a TypeScript/React SPA calls a versioned FastAPI REST API, which owns authentication, authorization and business rules. SQLAlchemy 2 maps a relational PostgreSQL (production target) or SQLite (local) schema. FastAPI OpenAPI is served at `/docs`. Vite proxies `/api/v1` to the local API; Nginx in Compose proxies the same path.

## Modules

- `backend/app/api/v1/auth.py`: separate auth router for account lifecycle, sessions, refresh, verification, recovery, logout and session-aware throttling.
- `backend/app/api/v1/routes.py`: existing product/campaign/application/referral/order/reward/analytics/admin route boundary (still consolidated and due to split in Phase 2).
- `backend/app/services/auth.py`, `security.py`: Argon2id/legacy rehash, HMAC-bound opaque refresh token, JWT session validation, one-use hashed actions, rate/origin policy.
- `backend/app/services/email.py`: explicit disabled-email provider and configurable SMTP adapter; header values are validated before transport.
- `backend/app/services/notifications.py`: transaction-aware notification and encrypted SQL email-outbox creation, idempotency, category preferences, and bounded worker retries. The worker CLI is `python -m app.worker`; it is a separate process and does not send mail during API requests.
- `backend/app/api/v1/notifications.py`: recipient-scoped paginated inbox/read/preferences APIs and admin-only redacted delivery telemetry.
- `frontend/src/components/Notifications.tsx`: in-app notification center, channel/category settings, and admin delivery monitor.
- `backend/app/services/rewards.py`: Decimal reward calculation service.
- `backend/app/models/entities.py`: mapped relational entities, including revocable auth sessions and one-use account tokens; Alembic migration owns deployed schema.
- `frontend/src/services/api.ts`: Axios auth client with access token in JS memory only, refresh-cookie session restoration, one refresh retry on 401, and session-expiration event.
- `frontend/src/components/AuthFlows.tsx`: login/registration/recovery/verification UI; `frontend/src/routes/access.ts` contains testable role page guards.

The schema and API are in a transition from initial single-file implementation; avoid converting to microservices or replacing the working product foundation. Roadmap Phase 2 splits business routes/services and centralizes resource policies. Creator matching remains deterministic weighted rules; no paid external AI API is required.

## Request flow

Browser -> relative `/api/v1/...` -> Vite/Nginx proxy -> FastAPI -> auth session and role/ownership checks -> SQLAlchemy transaction -> relational storage. Refresh cookie is HttpOnly; access bearer is short-lived and in-memory in the SPA. Business events and notification/outbox rows commit together. A separately deployed SQL poller claims and sends encrypted outbox messages through the existing SMTP adapter; the process is at-least-once, bounded to five attempts, and must use the same `JWT_SECRET` as the API. Run one worker per deployment: multi-process SQLite/PostgreSQL contention has not been stress-tested. SMTP acceptance is not inbox delivery and worker liveness is not currently measured. Payment settlement must only occur after provider signature/webhook verification; current local simulation is not settlement.
