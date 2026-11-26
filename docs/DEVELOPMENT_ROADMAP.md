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

Phases 1–3 are implemented. Phase 4 now covers the referral-attribution and conversion engine described in `docs/REFERRAL_ATTRIBUTION_AUDIT.md`. It reuses Referral/Application and commerce/payment records, and does not add a payment provider.

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

## API boundary prerequisite — Ownership and input hardening (P0, depends on Phase 1; continuing work)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Request/response schemas and validation | Phase 1 schemas | `app/schemas/`, routes | Replace `dict` for all sensitive writes; reject invalid enum, money, overlong strings and invalid IDs with stable 422s. | Positive/negative schema tests for each write route. |
| Centralize policy and ownership | Phase 1 principal/session | security/policy dependencies and routes | User sees/mutates only permitted resource; no arbitrary user IDs accepted from client for self-service; admin-only operations enforced server-side. | Cross-brand/cross-creator/customer tests on all private resource endpoints. |
| Abuse protection and safe errors | Phase 1 throttling | middleware/routes/logging | Consistent request IDs, safe error envelopes, no stack traces/secrets exposed; upload limits when uploads arrive. | Error contract, log capture/redaction, fuzz/limit tests. |

## Phase 2 — Complete customer commerce and order workflows (P0, built on the existing auth/product/referral foundation)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Product discovery and details | Existing product/brand rows | `backend/app/api/v1/commerce.py`, product fields/schema, `CustomerCommerce.tsx`, `/shop` routes/styles | Public server-side search/category/brand/effective-price/stock filters, sorting/paging; safe detail/gallery/specification/brand/program/related data; no hardcoded product results. | Backend filters/search/detail/empty and React query/error/empty component tests. |
| Persistent account cart | Phase 1 session/principal | `Cart`/`CartItem`, `0003_customer_commerce`, commerce API/client/UI | Per-account persistent DB cart; add/set/remove/clear; stock/active checks; server recalculates sale price and Decimal totals; client-supplied price rejected. Guest cart intentionally unsupported; checkout requires login. | Cart CRUD, DB persistence, ownership, stale-stock, amount-tampering tests; UI cart interaction tests. |
| Idempotent multi-line checkout | Cart/model and address validation | `CheckoutRequest`, order/customer/idempotency/address columns, `OrderItem`, API/UI | Required owner-scoped idempotency key; totals based only on DB prices; address validated; order, item snapshots, attribution and conditional stock decrement committed atomically; repeated key returns original order. | Replayed request, altered total, invalid address, inventory contention and order-snapshot tests. |
| Customer orders and lifecycle | Checkout | `/orders` customer view/detail/cancel/status, frontend orders pages | Customer can only read own records; unpaid pending/confirmed cancellation restores stock once; transition graph enforced; processing/shipment gated on trusted `paid` status. Preserve existing brand/creator/admin business views and legacy single-item endpoint. | Cross-customer denial, history/detail, repeated cancel, stock restore, lifecycle/role tests. |
| Referral continuity | Existing `/r/{code}` tracking and attribution rules | Signed HttpOnly referral-window cookie, cart summary/checkout, order referral FK | Existing referral route remains source of attribution; validate active/verified creator, active published campaign and product eligibility; no caller-supplied creator ID/code at new checkout; persist order referral relation. | Cookie tampering, campaign/product mismatch, expired/invalid referral and referral customer-journey API tests. |
| User-facing flow and evidence | Above endpoints | `CustomerCommerce.tsx`, `commerce.css`, App routes and docs | `/shop`, `/products/:id`, `/cart`, `/checkout`, `/orders`, `/orders/:id`; responsive accessible empty/loading/error states and actual API interactions. No false payment-completion message. | Vitest component/API tests, lint/typecheck/build. Browser E2E and production-grade DB concurrency tests remain release follow-ups. |

## Phase 3 — Payment options and order lifecycle (implemented; no gateway)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Payment records and extensible foundation | Phase 2 `Order` and checkout | `Order` metadata, `PaymentAttempt`, migration `0004_payment_options` | Fixed-precision amount/currency, method/status/reference/notes/confirmed actor/time and attempt idempotency; old orders backfill as `legacy`; no external SDK/provider abstraction scaffolding beyond the current order/attempt data model. | Fresh SQLite upgrade, downgrade/re-upgrade; invalid state/method constraints; PostgreSQL still unverified. |
| Demo payment | Payment attempt + server-derived checkout | `services/payments.py`, checkout, customer order UI | In-process backend simulation only. Success is tagged `DEMO-`, failure marks failed/cancelled and restores inventory; retries are idempotent; checkout never accepts a client-supplied paid state. Demo rewards are flagged non-payable and excluded from revenue/payout eligibility. | Success/failure, duplicate key/attempt, inventory restoration, referral reward and payout exclusion tests. |
| COD lifecycle | Payment attempts + admin authorization | commerce routes, admin order panel, audit log | COD is confirmed/unpaid at checkout; admins alone update fulfillment and confirm cash after delivery; collector/time/internal reference recorded once; COD cancellation clears the unpaid obligation and restores stock. | COD unpaid through fulfillment, unauthenticated/non-admin denial, duplicate collection, audit, cancellation/stock restore tests. |
| Disabled online and admin controls | Existing route guards | checkout selection, `/admin/orders` APIs/UI | Online is visibly disabled and server-rejected. Admin can search/filter orders, inspect payment attempts, update status, collect COD, and cancel eligible unpaid orders. | API role/filter tests and React checkout/admin-payment-detail tests. |
| Legacy and reporting safety | Prior simulator/public order endpoints | legacy `/orders`, analytics, rewards/payouts | Guest single-item checkout returns 410; historic rows are labelled `legacy`. Demo/legacy payments cannot be counted as genuine revenue or payout eligible; the migration marks legacy-linked historical rewards non-payable. | Guest endpoint rejection; demo analytics/payout exclusion. |

## Phase 4 — Referral attribution and conversion tracking (current)

Audit baseline and sequence: [`docs/REFERRAL_ATTRIBUTION_AUDIT.md`](REFERRAL_ATTRIBUTION_AUDIT.md). Reuse `Referral` as the creator/campaign link and accepted `Application` as participation; do not introduce a parallel collaboration or referral-link identity.

| Milestone | Plan | Acceptance criteria |
|---|---|---|
| 4.1 Data/policy foundation | Add product eligibility, durable visitor first/last touch, item-level attribution, conversion lifecycle/events and risk flags in additive migration `0005`; centralize eligibility. | Historical records retained; conversion uniqueness; date/status/application/product checks shared across click, checkout and conversion. |
| 4.2 Creator links/click tracking | Creator-owned generate/list/deactivate APIs; collision-safe codes; rate-limited click recording; signed opaque visitor cookie; sanitized privacy-conscious event data. | Only approved creators/campaigns/products; invalid link cannot replace attribution; repeated valid referrals use last-valid model. |
| 4.3 Commerce conversion lifecycle | Attribute only eligible order lines, prevent self-referral, persist a conversion transactionally with the order, confirm demo as simulated, leave COD pending until collection, mark cancellation terminal without deleting. | One conversion per order; duplicate requests safe; mixed cart only credits eligible lines; rewards use only eligible amount and retain demo flag. |
| 4.4 Analytics/UI/operations | Creator link/conversion dashboard; brand campaign aggregates; admin filters, risk review and audited deactivation; pagination/date filters. | Explicit metric definitions; no customer contact/address exposure; clicks/cart events never counted as conversions. |
| 4.5 Verification/documentation | Backend lifecycle/security/migration tests; frontend component tests; full referral-click-to-checkout integration test; docs and status updated. | Full required backend/frontend checks pass; known limits documented. PostgreSQL load, browser E2E and legal/privacy review remain separately reported if unverified. |

## Phase 5 — Complete creator/brand campaign operations (P1, depends on Phase 2)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Profile and verification management | Phase 2 schemas/ownership | profile routes/models/frontend | Full profile editing, creator social links (self-reported clearly), brand verification workflow, admin review. | Role and ownership tests; form and API tests. |
| Campaign CRUD/discovery/invites | Phase 2 policy | campaign routes/services/UI | Edit/draft/publish/pause and filters have real persistence; brand can invite; creator requirements enforced. | Lifecycle, filtering, RBAC tests. |
| Collaboration and deliverables | Campaign/application workflow | collaboration models/routes/UI/migration | Acceptance creates collaboration; deliverables revisions and approval are auditable and authorized. | Complete creator/brand workflow API and UI tests. |

## Phase 6 — Campaign lifecycle and trusted analytics (implemented locally; not a production-readiness claim)

Implementation record and metric definitions: [`docs/PHASE_6_ANALYTICS.md`](PHASE_6_ANALYTICS.md). The prior roadmap's genuine-payment Phase 6 is retained as a separate deferred workstream below; it was not a provider-integration deliverable.

| Milestone | Implementation | Acceptance / verification |
|---|---|---|
| 6.1 Campaign lifecycle | Brand-scoped list/detail/update, status transitions, structured campaign configuration, visibility and product scope; current models/services reused. | Brand ownership, product ownership, lifecycle, visibility and invalid date/configuration tests. |
| 6.2 Trusted analytics | Server-side UTC date windows and campaign/date/product scoping; existing order items, conversion/payment lifecycle, click/activity records and reward ledger only. | Decimal financial aggregation; no clicks-as-conversions, demo-as-revenue, unpaid COD-as-confirmed revenue or budget-as-spend. Mixed-cart item-level attribution regression test. |
| 6.3 Brand/admin reports | Brand overview, campaign, creator and product rollups; admin aggregate filters; rule-based observations and safe CSV outputs. | Role/ownership isolation and customer-PII exclusion; formula-injection escaping. Custom window capped at ten years. |
| 6.4 User experience | Brand campaign manager, analytics overview, campaign report, admin aggregates, date/product filters, empty/error/loading states. | Component coverage; API remains authoritative for filters and financial values. |
| 6.5 Migration/docs/checks | Additive `0007_campaign_intelligence` after `0006_rewards_ledger`; audit, implementation status, roadmap and metric definition docs. | SQLite fresh/existing upgrade tested. Downgrade intentionally retains fields to avoid destructive data loss; PostgreSQL remains unverified. |

Known scope boundaries: ROI/cost-per-conversion are unavailable without actual campaign-spend records; reward efficiency is not ROI. PostgreSQL, production load, browser E2E, payment/refund settlement and financial/legal review remain follow-ups. See the Phase 6 implementation record for exact commands/results and date attribution behavior.

## Deferred workstream — Genuine payment integration (separate from analytics Phase 6; outside Phase 3 scope)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Cart and order model | Product APIs/ownership | `Cart`/`CartItem`/`OrderItem`, migration `0003_customer_commerce`, commerce API/UI | **Implemented in Phase 2:** persistent account cart, multi-line Decimal totals, address snapshots, idempotency, inventory safety, ownership. Guest carts/address book/shipping quote remain unsupported. | Phase 2 coverage and limitations are recorded in `IMPLEMENTATION_STATUS.md`; PostgreSQL contention remains open. |
| Genuine provider adapter and verified settlement | Separate product/security approval, Order/PaymentAttempt records | Future provider adapter, signed webhook routes/config, reconciliation/refund operations | **Intentionally not implemented.** No provider chosen or connected. A later milestone must define signed webhooks, replay/idempotency, capture/refund/partial-refund, reconciliation, and separate handling from DEMO/COD. | Only after explicit approval: signature tamper/replay/idempotency, failure/cancel/refund and staging tests. No current live-money claims. |
| Attribution persistence | Referral model/cookie policy | Existing `/r/{code}` plus signed attribution cookie in commerce service | **Implemented for checkout continuity:** configured window, signed HttpOnly cookie, verified active creator/published campaign/product compatibility; referral FK stored on order. Consent/privacy/legal review and independent abuse review remain. | Cookie tamper, campaign and product validation, order association tests; expiry boundary/browser E2E follow-up. |

## Deferred workstream — Rewards, ledger and payout controls (P0 financial, depends on Phase 4)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Reward lifecycle worker | Verified paid/refund events | rewards service, worker, migration | Idempotent pending → eligible → approved/paid; cancel/reverse refunds and disputes; campaign limits lock-safe. | Duplicate event, partial refund, budget race and lifecycle tests. |
| Ledger and payout approval | Reward lifecycle | ledger/payout services/admin routes/UI | Immutable balanced entries, transactional payout reservation and audited admin approve/reject/paid controls; no frontend balance authority. | Ledger invariant, concurrent payout, audit and role tests. |

## Phase 7 — Secure platform administration (implemented locally; not a production-readiness claim)

Audit and implementation record: [`PHASE_7_ADMIN_AUDIT.md`](PHASE_7_ADMIN_AUDIT.md) and [`PHASE_7_ADMIN.md`](PHASE_7_ADMIN.md). This phase extends the Phase 1 auth/session, Phase 4 risk, Phase 5 ledger and Phase 6 campaign systems rather than creating duplicates.

| Milestone | Implementation | Acceptance / verification |
|---|---|---|
| 7.1 Lifecycle and restrictions | Bounded admin user search with masked email; reasoned/typed account activation and suspension; transactional session revocation; self-suspension and last-active-admin guards; role mutation prohibited. | Admin-only APIs; existing sessions invalidated; request role injection rejected. |
| 7.2 Manual verification/moderation | Manual creator/brand status review; constrained campaign moderation with reason and confirmation; legacy admin campaign status route no longer bypasses reasoned moderation. | Uses existing profiles/campaign lifecycle; no external verification claim; audit event for action. |
| 7.3 Risk and disputes | Existing `ReferralRiskFlag` is the investigation source; human reasons and dispositions; append-only dispute events linked to existing order/conversion/reward records. | No automatic weak-signal ban; dispute operations do not edit conversions, rewards, or ledger. |
| 7.4 Admin audit and operations UI | Additive `0008_platform_admin`; append-only administrative event history; platform queue counts, bounded search and role-gated responsive operations UI. | API liveness/database probe/integrations stated separately; absent notification/email/Redis health is not fabricated. |
| 7.5 Verification | Backend role/lifecycle/risk/moderation/dispute/immutability tests; frontend component coverage; SQLite fresh/historical upgrade and downgrade/re-upgrade. | Backend 57 passed; frontend 35 passed; compile, TS, lint/build passed. PostgreSQL, browser E2E, independent security and production review remain unverified. |

## Deferred financial follow-up — Reward lifecycle worker and payout controls

The planned worker, actual payout settlement and refund lifecycle remain future work. Phase 5 already implements rule-based reward generation, simulated payout disclosure, immutable ledger entries, reversal entries, and admin reward review; it does not implement a scheduled eligibility worker, actual payout approval/transfer, gateway refunds or accounting settlement.

## Phase 8 — Reporting, discovery and trust (P1, depends on validated data)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Analytics (Phase 6 first release implemented) | Verified order/reward data | `app/services/analytics.py`, `app/api/v1/analytics.py`, `app/api/v1/campaigns.py`, `CampaignIntelligence.tsx` | Database-derived aggregates, UTC date/product filters, campaign/creator/product tables, honest empty states and safe exports. Remaining: PostgreSQL query-plan/load verification and production browser E2E. | SQLite aggregation/ownership/privacy/CSV tests and frontend component tests; see `docs/PHASE_6_ANALYTICS.md`. |
| Creator scores and risk review | Verified events | scoring/risk models/services/admin UI | Configurable explainable formula and review workflow; no unsupported fraud claims. | Deterministic component weights and review authorization tests. |
| Creator matching | Profiles/campaign filters | matching service/routes/UI | Weighted explainable recommendations use available verified/self-entered data and expose reasons/limits. | Ranking, missing-data and access tests. |

## Phase 9 — Messaging, notifications, admin completion (P1, depends on Phase 2)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Conversations/notifications/email | Verified users and collaboration | models/routes/services/UI | Persisted authorized conversations, read/unread, preferences; provider abstraction reports disabled mode honestly. | Access, unread state, provider and delivery failure tests. |
| Remaining admin bootstrap/operations gaps | Phase 7 admin foundation | deployment provisioning, notifications, support workflows | Safely provision an initial admin; implement persisted notification/support workflows only when delivery is configured. Phase 7 account controls, risk, disputes and audit are implemented. | Provisioning controls, delivery/access tests; existing Phase 7 checks in `docs/PHASE_7_ADMIN.md`. |

## Phase 10 — Production readiness (P0 release gate; depends on all P0 work)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Operational/security hardening | Phases 1–7 | Docker, deployment docs, config, CI | Managed DB, TLS, secrets, backups, health/metrics, CSP, dependency scans, migration rollback and incident runbook. | CI, E2E, migration, SAST/dependency scan, load/security review. |
| Accessibility/performance/release review | Working journeys | frontend, observability/docs | Keyboard/mobile/a11y pass, route code splitting, privacy/retention and legal review, staged release plan. | Playwright critical journeys, axe/a11y, bundle and performance budgets. |

## Current phase

- **Audit and roadmap:** complete; the original branch baseline and prior Phase 1/2 evidence are recorded above and in `IMPLEMENTATION_STATUS.md`.
- **Phase 1 authentication/security:** implemented and pushed in `16f995e`; additive migration `0002_auth_security`, Argon2id/legacy upgrade, revocable sessions, rotating HttpOnly refresh cookie, email verification/recovery, rate limits, origin checks, production configuration validation, in-memory-only access tokens and role-aware UI.
- **Phase 2 customer commerce:** implemented and pushed in `f40dae1`; additive migration `0003_customer_commerce`, API-backed catalog, persistent customer cart, idempotent checkout, conditional inventory handling, ownership-scoped orders, signed referral continuity and responsive shop UI.
- **Phase 3 payment options/order lifecycle:** implemented in the current milestone; migration `0004_payment_options`, backend-only no-money Demo Payment, COD unpaid/fulfillment/administrator collection, disabled Online Payment, payment-attempt history, admin order management, audit records, demo-reward non-payability and removal of legacy guest simulator. See `docs/PAYMENT_OPTIONS.md` and `IMPLEMENTATION_STATUS.md` for verified test results and limitations.
- **Phase 4 (implemented on the current development branch; verified in SQLite/local test environments):** referral attribution and conversion tracking. Reuses existing Referral/Application and commerce/payment records; attribution rules and verification evidence are in `docs/referral-attribution.md`, `docs/REFERRAL_ATTRIBUTION_AUDIT.md`, and `IMPLEMENTATION_STATUS.md`. PostgreSQL migration/concurrency, browser E2E, privacy/legal review, and paid-order refund workflow remain release follow-ups. No production-ready claim is made.
- **Phase 6 (implemented on the current branch; local verification passed):** campaign management and trusted brand/admin analytics. Backend 53 tests and frontend 32 tests pass; lint/build, SQLite migration coverage, compileall and diff checks passed. Audit, definitions, results and limitations are recorded in `docs/PHASE_6_ANALYTICS_AUDIT.md` and `docs/PHASE_6_ANALYTICS.md`. PostgreSQL and browser E2E remain unverified.
- **Phase 7 (implemented on the current branch; local verification passed):** secure platform administration, session-revoking restrictions, manual verification and campaign moderation, human risk investigation, disputes with append-only event history, immutable admin audit events and operations UI. Backend 57 tests and frontend 35 tests pass; SQLite migration and local quality checks passed. PostgreSQL, browser E2E and production readiness remain unverified; see `docs/PHASE_7_ADMIN_AUDIT.md` and `docs/PHASE_7_ADMIN.md`.
