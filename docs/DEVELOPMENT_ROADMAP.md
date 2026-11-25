# CROWND 2.0 — Verified audit and development roadmap

Audit date: 2026-11-25. Audited current branch source and ran `git status`, branch/log/remote inspection. This roadmap supersedes estimates in the earlier status note; items marked implemented are verified in source only where explicitly described.

## Repository audit: findings

### Current state and architecture

The repository is not a legacy multi-module app: its initial commit was a README; commit `75601c8` added a FastAPI/SQLAlchemy backend, a React/Vite SPA, docs, tests and local Docker configuration. Working branch is `arena/e6c9b4f7-crownd-2-0`, remote `origin` points at the requested GitHub repository, and the initial audit found a clean worktree.

- Backend: `backend/app/main.py`, one consolidated `api/v1/routes.py`, global `Base.metadata.create_all()` at import, module-global engine/session, entities in one model file, security helpers in one module.
- Frontend: a very large single `frontend/src/App.tsx`, token/user persistence in `localStorage`, one Axios interceptor, client-side route switching (no protected route/React Router routes), one stylesheet, TanStack Query for some server state.
- Database: users/profiles, products, campaigns, applications, referrals/clicks, orders, rewards, ledger, payouts and audit logs. FKs and a few uniqueness constraints exist, but ORM relationships/cascades and session/token lifecycle tables do not. Initial Alembic migration delegates to `Base.metadata.create_all`, not explicit reviewed DDL.
- API currently exposes health; registration/login/me; creator list/profile edit; campaign list/create/detail/status; applications; products; referral clicks/list; single-item order creation/list; rewards/payout request; aggregate analytics; basic AI matching; admin user/audit read APIs.
- Tests are a small in-memory SQLite workflow suite; frontend tests cover currency/reward helpers. No browser E2E suite.

### Verified working behaviors

- SQLAlchemy models and startup run; earlier preview smoke tests returned health and seeded campaigns. The source has registration/login with PBKDF2-HMAC-SHA256, signed access JWT, active-user lookup, role dependency checks, product/campaign/application/referral/order/reward APIs, Decimal reward utility, analytics and demo seed.
- Signup creates creator/brand profile rows and returns an access token immediately. Brand campaign ownership checks and application review ownership checks are server-side. Creator application duplicate and order-reward uniqueness have database constraints.
- Local payment simulation is explicitly gated by development + simulator configuration; it is not an actual payment integration.

### Security, correctness and product risks verified in source

- Access bearer tokens and a user snapshot persist in `localStorage`; there is no refresh token, session record, revocation, logout API, email verification, reset workflow, lockout or rate limiter. JWT secret has a weak development fallback and password hashing uses custom PBKDF2 parameters, not a standard Argon2id library.
- Registration allows caller-supplied roles from an allowlist but logs the user in before verifying the email; admin role cannot be self-registered. JWT role claim is not the authority (DB role controls route checks), but tokens are not persisted/revocable.
- Public campaign/product list endpoints expose data by design; referral tracking is public. Orders are unauthenticated guest requests and accept only explicit code attribution. Several list endpoints do not consistently enforce paging/ownership beyond current scope.
- Body payloads are generic dicts with scattered validation. Auth endpoints are brute-forceable. No request-origin/CSRF guard for cookie auth exists because cookies are not used yet. CORS allowlist is configurable, but secure production validation and proxy-origin behavior are not enforced.
- UI treats localStorage contents as authenticated without revalidating `/auth/me`; login/registration are the only auth form state. There is no protected-route guard or real session-expiry handling. UI role-specific navigation is mostly generic. Some buttons only notify instead of performing the named action. Charts contain explanatory/sample-like content and campaign demo fallback records exist in source.
- Several routes that return private records have incomplete ownership semantics for customer/brand/etc; admin is not bootstrapped; orders are single-item and unauthenticated. The simulator directly marks an order paid based on request body in dev only, so it must never be enabled outside local development. Reward release/refund/reversal/payout processing is missing.
- Application route handlers are tightly coupled; `create_all` during app import can silently mutate deployed schemas; migration is not safely incremental. Test code sets environment after imports in a way that may not affect already loaded settings, and shared global DB override/test state can contaminate expanded tests.

### Phase sequence

The authentication/security hardening phase is first. Do not implement real payments or payouts until money lifecycle safeguards are specified and tested. Dependencies between phases are called out below.

## Phase 1 — Authentication and security foundation (P0, now)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Audit baseline and plan | None | `docs/DEVELOPMENT_ROADMAP.md`, status/docs | Current tree, risks and incremental work are documented from source; existing services and branch preserved. | Git status/history inspection; run existing backend/frontend suites and keep baseline results. |
| Strong password hashing and input schemas | None | `backend/requirements.txt`, `app/security.py`, `app/schemas/auth.py`, auth route/service | Argon2id (standard maintained implementation) for new secrets; verify legacy PBKDF2 hashes for seamless existing account login and rehash on success; validated email/password/name bounds; generic invalid-login response. | Hash/verify, legacy upgrade, malformed/oversized input tests. |
| Persistent sessions, refresh rotation, revocation | DB/schema work | `models/entities.py`, new migration, auth service/routes/security, config | Short-lived access JWT; random opaque refresh token in Secure/HttpOnly/SameSite cookie, only its digest stored; rotating refresh token; replay/revocation/expiry rejected; logout revokes current session; protected API checks live session so revoked session access is denied. Local cookie security is configurable; production refuses unsafe secrets/cookie settings. | Access expiry, refresh rotation, replay, logout/revocation, cookie attributes, cross-user tests. |
| Email verification and password recovery | Email abstraction | auth token model/service, `app/services/email.py`, auth routes, config, frontend auth pages | Purpose-scoped one-use expiring hashed tokens; registration remains unverified until confirmation; reset does not disclose account existence; reset revokes existing sessions. SMTP provider is only called when explicitly configured; disabled development provider truthfully says message was not sent. | Verification success/expired/replay; reset success/expired/replay; enumeration-safe response; fake provider and disabled provider tests. |
| Throttling and origin controls | Shared storage design | config, middleware/dependencies, auth routes, Compose/docs | Per-client rate limits on login, registration, refresh, reset and verification; shared production limiter backend required in production; trusted-origin policy for cookie endpoints; no secrets/tokens/passwords in logs. | Limits trip/reset; production startup config rejection; origin/CSRF negative tests; log redaction check. |
| Frontend auth lifecycle | Backend endpoints above | API client, auth/session context, protected routes, role-aware navigation, auth modal/pages | Access token held in memory only; bootstrapping calls refresh, then `/auth/me`; refresh on 401 once, logout clears state and revokes; protected screens redirect to login; role guards and loading/error/session-expiry views. | API-client tests, route/role tests, session boot/reload/logout/expiry tests; lint/typecheck/build. |
| Migrations and compatibility | Schema updates | Alembic versions, migration guide, `main.py` | Explicit additive migration introduces sessions/auth tokens/verification state; app startup no longer creates production schema implicitly; existing SQLite/Postgres rows remain usable and old hashes still authenticate. | Upgrade empty DB and pre-change DB fixture; migration head and backend suite. |

## Phase 2 — Ownership and API boundary hardening (P0, depends on Phase 1)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Request/response schemas and validation | Phase 1 schemas | `app/schemas/`, routes | Replace `dict` for all sensitive writes; reject invalid enum, money, overlong strings and invalid IDs with stable 422s. | Positive/negative schema tests for each write route. |
| Centralize policy and ownership | Phase 1 principal/session | security/policy dependencies and routes | User sees/mutates only permitted resource; no arbitrary user IDs accepted from client for self-service; admin-only operations enforced server-side. | Cross-brand/cross-creator/customer tests on all private resource endpoints. |
| Abuse protection and safe errors | Phase 1 throttling | middleware/routes/logging | Consistent request IDs, safe error envelopes, no stack traces/secrets exposed; upload limits when uploads arrive. | Error contract, log capture/redaction, fuzz/limit tests. |

## Phase 3 — Complete creator/brand campaign operations (P1, depends on Phase 2)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Profile and verification management | Phase 2 schemas/ownership | profile routes/models/frontend | Full profile editing, creator social links (self-reported clearly), brand verification workflow, admin review. | Role and ownership tests; form and API tests. |
| Campaign CRUD/discovery/invites | Phase 2 policy | campaign routes/services/UI | Edit/draft/publish/pause and filters have real persistence; brand can invite; creator requirements enforced. | Lifecycle, filtering, RBAC tests. |
| Collaboration and deliverables | Campaign/application workflow | collaboration models/routes/UI/migration | Acceptance creates collaboration; deliverables revisions and approval are auditable and authorized. | Complete creator/brand workflow API and UI tests. |

## Phase 4 — Customer commerce and verified payments (P0 financial, depends on Phase 2)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Cart and order model | Product APIs/ownership | cart/order schemas/models/migrations/frontend | Multi-line cart, inventory validation/locking, customer account and guest rules, correct order states. | Inventory race, totals, ownership and checkout tests. |
| Payment provider abstraction | Order model, credentials | payment adapter, webhook routes/config, UI | Razorpay test-mode adapter only when configured; backend signature verification, webhook dedupe/idempotency; frontend callback cannot mark paid; simulator remains development-only. | Signature tamper/replay/idempotency, failed/cancelled/refund tests; no live-money claims. |
| Attribution persistence | Referral model/cookie policy | attribution service/middleware and checkout | Configurable last-valid referral window, consent/privacy policy, creator/campaign/product eligibility. | Window boundaries, code override, invalid/expired/cross-product tests. |

## Phase 5 — Rewards, ledger and payout controls (P0 financial, depends on Phase 4)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Reward lifecycle worker | Verified paid/refund events | rewards service, worker, migration | Idempotent pending → eligible → approved/paid; cancel/reverse refunds and disputes; campaign limits lock-safe. | Duplicate event, partial refund, budget race and lifecycle tests. |
| Ledger and payout approval | Reward lifecycle | ledger/payout services/admin routes/UI | Immutable balanced entries, transactional payout reservation and audited admin approve/reject/paid controls; no frontend balance authority. | Ledger invariant, concurrent payout, audit and role tests. |

## Phase 6 — Reporting, discovery and trust (P1, depends on validated data)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Analytics | Verified order/reward data | analytics services/routes/charts | Database-derived aggregates, date filters, efficient paging and truly empty states. | Query scope, aggregation and date-boundary tests. |
| Creator scores and risk review | Verified events | scoring/risk models/services/admin UI | Configurable explainable formula and review workflow; no unsupported fraud claims. | Deterministic component weights and review authorization tests. |
| Creator matching | Profiles/campaign filters | matching service/routes/UI | Weighted explainable recommendations use available verified/self-entered data and expose reasons/limits. | Ranking, missing-data and access tests. |

## Phase 7 — Messaging, notifications, admin completion (P1, depends on Phase 2)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Conversations/notifications/email | Verified users and collaboration | models/routes/services/UI | Persisted authorized conversations, read/unread, preferences; provider abstraction reports disabled mode honestly. | Access, unread state, provider and delivery failure tests. |
| Admin operations/risk/disputes | Audit log and policy | admin routes/models/UI | Admin account bootstrap safely; review queues and sensitive actions audited and reversible per policy. | Admin-only/other-role denial and audit assertions. |

## Phase 8 — Production readiness (P0 release gate; depends on all P0 work)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Operational/security hardening | Phases 1–7 | Docker, deployment docs, config, CI | Managed DB, TLS, secrets, backups, health/metrics, CSP, dependency scans, migration rollback and incident runbook. | CI, E2E, migration, SAST/dependency scan, load/security review. |
| Accessibility/performance/release review | Working journeys | frontend, observability/docs | Keyboard/mobile/a11y pass, route code splitting, privacy/retention and legal review, staged release plan. | Playwright critical journeys, axe/a11y, bundle and performance budgets. |

## Current phase

- **Audit and roadmap:** complete. The initial branch was clean at `75601c8`; baseline tests/build and the existing preview/API were verified.
- **Phase 1 authentication/security:** implemented in this branch; additive migration `0002_auth_security`, Argon2id/legacy upgrade, revocable sessions, rotating HttpOnly refresh cookie, email verification/recovery with explicit SMTP/no-send modes, rate limits, origin checks, production configuration validation, in-memory-only access tokens, protected UI and role navigation. See `IMPLEMENTATION_STATUS.md` for current test evidence.
- **Next:** Phase 2 API schema and comprehensive resource policy hardening; then creator/brand operational breadth. Payment verification and financial releases remain blocked until Phases 2 and 4/5 are complete.
