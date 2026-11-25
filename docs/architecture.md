# Architecture

CROWND is a modular monolith: a TypeScript/React SPA calls a versioned FastAPI REST API, which owns authentication, authorization and business rules. SQLAlchemy 2 maps a relational PostgreSQL (production target) or SQLite (local) schema. FastAPI OpenAPI is served at `/docs`. The Vite dev server proxies `/api/v1` to the local API; Compose's Nginx frontend proxies the same path to `api`.

## Modules

- `backend/app/api/v1/routes.py`: current HTTP boundary for auth, profiles, products, campaigns, applications, referral, order, rewards, analytics and admin reads.
- `backend/app/services/rewards.py`: Decimal reward calculation service.
- `backend/app/security.py`: password hashing, JWT minting and role/current-user dependencies.
- `backend/app/models/entities.py`: mapped relational entities; `database.py` centralizes engine/session dependencies.
- `frontend/src/App.tsx`: responsive public shell and role workspaces; `services/api.ts` is the typed Axios setup/token interceptor.

This is an initial implementation foundation, not a final separation into repositories/use-cases. Routes are currently consolidated and should be modularized as features grow. Avoid external paid AI APIs; creator match recommendations are weighted deterministic rules with displayed factors.

## Request flow

Browser -> relative `/api/v1/...` -> Vite/Nginx proxy -> FastAPI -> role/ownership check -> SQLAlchemy transaction -> relational storage. Payments must only move order state after verified provider callbacks in the future; current local simulation is explicitly not settlement.
