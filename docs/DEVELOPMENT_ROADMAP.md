# CROWND 2.0 — Verified audit and development roadmap

Audit date: 2026-11-25. This roadmap preserves the historical Phase 1–9 audit below and now includes Phase 10 completion and Phase 11 execution evidence. Phase 10 is committed at `1cda7d3`. Phase 11 found no Docker/container runtime, PostgreSQL client/server tools, `age`, or runnable browser; a disposable SQLite API/Vite/worker smoke passed, but it does not validate PostgreSQL or Compose. An existing connected Supabase PostgreSQL project was observed via metadata only and was not used because it is not confirmed isolated; the user chose a different isolated target, which has not yet been supplied through a secure mechanism. Exact evidence and blockers are in `docs/PHASE_11_INFRASTRUCTURE_VALIDATION.md`, `docs/PHASE_11_VALIDATION_RESULTS.md`, and `docs/PHASE_11_HOSTING_EVALUATION.md`. This roadmap does not claim production readiness.

## Latest infrastructure phase status

- **Phase 10:** hardening and release documentation completed and pushed (`1cda7d3`). Local tests and dependency audits passed as documented; Docker/PostgreSQL/backup-restore/SMTP/browser/deployment checks were explicitly not run then.
- **Phase 11:** initial execution attempted. Debian 12 sandbox has no Docker/Compose/alternative runtime or PostgreSQL tools; no system packages were installed. Fresh Alembic migration on a newly created disposable SQLite DB reached `0009_notifications`; host-run FastAPI/Vite health and seeded brand login returned HTTP 200; worker disabled-provider suppression, heartbeat, graceful stop and restart passed against that SQLite DB. Playwright Chromium could not start due missing `libnspr4.so`; no E2E workflow ran. Supabase connector metadata showed a healthy PostgreSQL 17 service and existing CROWND-labelled SQL migration history, but the project is not confirmed disposable and was not modified.
- **Current release assessment:** infrastructure validation incomplete; no provider selected, account/plan/credentials provisioned, backup/restore rehearsal, SMTP relay test, browser E2E, staging deployment or production smoke test. The user chose a different isolated PostgreSQL target (not yet supplied through a secure mechanism) and deferred Docker installation; use an approved Docker/browser-capable runner before resuming those checks.

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

## Deferred follow-up — Reporting, discovery and trust (the analytics foundation is Phase 6)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Analytics (Phase 6 first release implemented) | Verified order/reward data | `app/services/analytics.py`, `app/api/v1/analytics.py`, `app/api/v1/campaigns.py`, `CampaignIntelligence.tsx` | Database-derived aggregates, UTC date/product filters, campaign/creator/product tables, honest empty states and safe exports. Remaining: PostgreSQL query-plan/load verification and production browser E2E. | SQLite aggregation/ownership/privacy/CSV tests and frontend component tests; see `docs/PHASE_6_ANALYTICS.md`. |
| Creator scores and risk review | Verified events | scoring/risk models/services/admin UI | Configurable explainable formula and review workflow; no unsupported fraud claims. | Deterministic component weights and review authorization tests. |
| Creator matching | Profiles/campaign filters | matching service/routes/UI | Weighted explainable recommendations use available verified/self-entered data and expose reasons/limits. | Ranking, missing-data and access tests. |

## Phase 8 — Notifications, communication and workflow automation (implemented locally; not a production-readiness claim)

Audit and implementation record: [`PHASE_8_NOTIFICATIONS_AUDIT.md`](PHASE_8_NOTIFICATIONS_AUDIT.md) and [`PHASE_8_NOTIFICATIONS.md`](PHASE_8_NOTIFICATIONS.md). The feature reuses existing account, commerce, campaign, reward, SMTP and admin systems; it introduces no second auth/business system or external broker.

| Milestone | Implementation | Acceptance / verification |
|---|---|---|
| 8.1 Persistence and idempotency | Additive `0009_notifications` creates recipient-scoped notifications, category preferences and encrypted email outbox. Unique `(recipient_id,event_key)` constraints and same-transaction inserts protect duplicate business events. | SQLite fresh/historical migration and re-upgrade tests; PostgreSQL not verified. |
| 8.2 Delivery worker and provider | Extend existing disabled/SMTP provider boundary; one-use verification/reset payloads are Fernet-encrypted at rest. Separate `python -m app.worker` SQL poller applies bounded exponential retry (five attempts), stale-claim recovery and static error codes. | No API request performs SMTP I/O. SMTP disabled is recorded as suppressed, not sent. At-least-once provider handoff; one worker supported, multi-process/PostgreSQL contention unverified. |
| 8.3 Event integration and APIs | Transactional events cover checkout/COD/demo states, cancellation and admin order status/collection, campaign application/submission/review/moderation, reward creation/review/simulated payout, password reset and account lifecycle. Inbox, read/read-all, preferences and admin-only redacted delivery telemetry are authenticated. | Recipient scoping, pagination, preferences, event idempotency, unsafe URL/header rejection, generic reset behavior and no real money/shipping claims tested. |
| 8.4 User/admin surfaces | Role-aware sidebar and unread bell badge; inbox, channel/category settings and admin delivery monitor; operations overview distinguishes SQL outbox, SMTP configuration and unmeasured worker health. | React escapes body text; no email address, content, ciphertext, tokens or provider details in admin API/UI. |
| 8.5 Verification and operations | Backend API/worker/migration tests; frontend inbox/settings/admin monitor tests; docs, project status and roadmap updated. Compose includes a distinct worker service and local Mailpit. | Report actual local check results in `docs/PHASE_8_NOTIFICATIONS.md`; production SMTP/inbox, PostgreSQL, browser E2E and production worker liveness remain unverified. |

Explicit limits: SMTP acceptance does not prove delivery; a queue worker must run with the same database and `JWT_SECRET`; changing that secret with pending encrypted rows causes those messages to fail decryption. This is an at-least-once system (a crash after provider acceptance can cause a duplicate); only one worker should be operated until multi-process testing is completed. Disabled email suppresses the queue and new users cannot verify/login. No conversation/messaging module, external email provider, real payment/payout/refund/shipping integration, or automatic dispute/risk actions are implied.

## Phase 9 — System-wide QA and defect correction (local verification completed; release blockers remain)

Phase 9 is validation and repair, not a feature phase. Audit scope, confirmed defects, reproduction/root causes, fixes and residual risks: [`PHASE_9_QA_AUDIT.md`](PHASE_9_QA_AUDIT.md). Exact executed outcomes and unavailable checks: [`PHASE_9_TEST_RESULTS.md`](PHASE_9_TEST_RESULTS.md).

| Milestone | Result | Evidence / remaining limitations |
|---|---|---|
| 9.1 Role/ownership and sensitive boundaries | Targeted route/test review and existing cross-role tests exercised across customer, creator, brand and administrator flows. | Backend suite passed; review is not exhaustive endpoint fuzzing or independent penetration testing. |
| 9.2 Commerce and seller lifecycle | Fixed mixed-brand order visibility and suspended-brand catalog/campaign/cart/checkout eligibility; added regressions for visibility, unavailable cart state, order suppression and stock preservation. | Regressions and full backend suite passed locally on SQLite. No PostgreSQL checkout contention test. |
| 9.3 Session and admin concurrency risks | Reproduced and fixed refresh-token double rotation using conditional compare-and-swap; added synchronized SQLite regression. Added stable admin-cohort row locking for last-admin suspension risk found during code review. | Refresh regression passed; admin race was not reproduced/tested concurrently. PostgreSQL row locks remain unverified. |
| 9.4 Integration, frontend, migrations and hygiene | Backend **68 passed**; frontend **38 passed**; lint/build (including `tsc -b`), compileall and diff check passed. Temporary SQLite copy upgraded from `0005` to `0009`, integrity `ok`, no FK violations. npm audit reported 0 vulnerabilities. | Existing warnings and small migration-data sample documented. `pip-audit`/Bandit, browser E2E, PostgreSQL and external services unavailable or not run. |

Phase completion means the listed local checks were executed successfully, not that every business path is correct or that the system is production-ready. The original local database remains at Alembic `0005_referral_attribution`; only a temporary copy was upgraded. PostgreSQL, browser E2E, broad load/concurrency testing, external provider delivery, independent security review and privacy/legal review remain open.

## Phase 10 — Production readiness (P0 release gate; depends on Phases 1–9 and other release blockers)

| Task | Dependencies | Files/modules | Acceptance criteria | Testing |
|---|---|---|---|---|
| Operational/security hardening | Phases 1–7 | Docker, deployment docs, config, CI | Managed DB, TLS, secrets, backups, health/metrics, CSP, dependency scans, migration rollback and incident runbook. | CI, E2E, migration, SAST/dependency scan, load/security review. |
| Accessibility/performance/release review | Working journeys | frontend, observability/docs | Keyboard/mobile/a11y pass, route code splitting, privacy/retention and legal review, staged release plan. | Playwright critical journeys, axe/a11y, bundle and performance budgets. |

## Phase 12 — Existing product feature audit and completion (in progress; local validation passes; substantial scope and infrastructure blockers remain)

Audit scope, per-module COMPLETE/PARTIAL/MISSING/BROKEN/PLACEHOLDER/DISCONNECTED/UNVERIFIED classifications, P0–P3 priorities, confirmed fixes and residual work: [`PHASE_12_FEATURE_AUDIT.md`](PHASE_12_FEATURE_AUDIT.md). Implementation decisions and executed verification: [`PHASE_12_IMPLEMENTATION_LOG.md`](PHASE_12_IMPLEMENTATION_LOG.md). This phase makes targeted additions to the current product; it is not a redesign or rewrite.

| Milestone | Result | Evidence / remaining limitations |
|---|---|---|
| 12.1 Audit and baseline | Completed from API/routes/services, schema/migrations, frontend paths/pages, existing tests and prior phase audits. | Baseline: backend 74 passed; frontend 38 passed, lint/build passed. No external infrastructure or browser E2E claim. |
| 12.2 Profile and application workflows | Added strict bounded schemas; creator-profile missing-record/ownership/uniqueness handling; idempotent repeated application-review state; explicit allowed transitions and row lock. | New regression cases cover malformed/extra/null/empty inputs, role/ownership denials, duplicates, missing records and duplicate-side-effect prevention. |
| 12.3 Dashboard/navigation truthfulness | Removed dashboard/discovery sample fallback and nonfunctional controls; real notifications power recent activity; retry/empty/loading/error states and current date; removed dead-end Messages/invitation actions; creator discovery uses saved bios with creator-reported-metric disclosure and hides unproven scores; `/applications` role guard. | Public hero example is labeled illustrative and invented amounts/creator handle removed. Server authorization remains the security boundary. |
| 12.4 Owner-scoped brand catalog | Added authenticated paginated `/brand/products`, explicit stock in create form, cached list refresh and owner/role/paging tests. | Product edit/archive and richer catalog management remain P2. |
| 12.5 Role-aware profiles and brand catalog lifecycle | Added profile forms/API, brand product updates/stock/soft status and reasoned admin product moderation. | 4 new backend regression tests plus profile/product/admin UI integration tests; no migration. Product rows are never hard deleted. |
| 12.6 Creator/application integration and disputes | Fixed platform search and creator review action permissions; added order-owner dispute intake, reporter status and notifications, preserving financial state. | Backend 81 passed; frontend 54 across 14 files; lint/build, compileall and `npm audit --omit=dev` passed (0 vulnerabilities). `pip-audit` absent. |
| 12.7 Verification and remaining scope | Audit expanded to modules A–M with evidence/status/priority. | Starlette/httpx deprecation and Recharts jsdom warnings remain. PostgreSQL, Docker/Compose, backup/restore, actual SMTP delivery, browser E2E, deployment and production smoke checks were not run. |

Current Phase 12 estimate: **80%** (scope estimate, not a test-derived KPI). Local fixes and automated regression checks are substantially complete; external runtime validation and the listed product gaps remain. Residual priorities: **P0** Phase 11 infrastructure checks; **P1** PostgreSQL concurrency and broader security/accessibility review; **P2** creator invitations, dispute evidence, messaging, saved addresses and product catalogue enhancements; **P3** support destination and specified dashboard date ranges. Payment remains simulated demo plus COD only.

## Phase 13 — Cross-module integration and transition reliability (in progress; not complete)

Audit findings, workflow disposition and unresolved risks: [`PHASE_13_INTEGRATION_AUDIT.md`](PHASE_13_INTEGRATION_AUDIT.md). Implementation and executed evidence: [`PHASE_13_IMPLEMENTATION_LOG.md`](PHASE_13_IMPLEMENTATION_LOG.md). Work remains incremental; preserve existing behavior and do not redesign the UI.

| Workstream | Local implementation/evidence | Outstanding |
|---|---|---|
| Referral/order/reward/analytics journey | Checkout reward terms are snapshotted per attributed order item; mixed-cart creator conversion views report only that creator's items. COD integration asserts persisted frozen-rate reward and creator-scoped attribution lines. | Isolated PostgreSQL query, concurrency and reporting reconciliation.
| Cancellation, inventory and idempotency | Cart-first locking, stable product lock ordering, conditional stock reservation, repeat idempotency lookup, savepoint recovery for first-cart creation. Existing cancel/restock and replay coverage retained. | PostgreSQL simultaneous checkout/cart mutation/cancel stress tests.
| COD collection, suspension and campaign lifecycle | Rewards use checkout terms at collection; inactive creators are barred from approval/simulated payout; campaign acceptance/publication checks active participants/products; relevant rows locked. | Concurrent suspension/acceptance/payout and publication/product-state races on PostgreSQL.
| Disputes, ledger and events | Disputes hold linked rewards and release only after final active case; status is flushed before querying; ledger IDs/amounts/directions asserted unchanged; order-item history append-only. | PostgreSQL concurrent dispute/collection tests, live SMTP and multi-worker dedupe.
| Schema / regression | Additive Alembic `0010_integration_snapshots`; migration tests remove 0010 fields from a disposable pre-upgrade SQLite schema and verify column addition plus rejecting UPDATE/DELETE triggers. Backend: **84 passed, 4 skipped** (the four PostgreSQL-only migration/concurrency tests); frontend: **54 passed across 14 files**, lint/build/typecheck passed. | PostgreSQL tests are not executed: no local server/tools, endpoint or explicit disposable DB approval. SMTP, browser E2E, Docker/Compose, backup/restore, deployment and production smoke remain unverified.

**Phase 13 completion is not claimed.** Supabase/production data was not used. No PostgreSQL, Docker/Compose, browser E2E, SMTP acceptance, backup/restore, deployment or production smoke test was performed. The existing Phase 11 infrastructure blocker remains. The current result is local backend implementation and SQLite regression evidence, not production readiness.

## Current phase

- **Audit and roadmap:** complete; the original branch baseline and prior Phase 1/2 evidence are recorded above and in `IMPLEMENTATION_STATUS.md`.
- **Phase 1 authentication/security:** implemented and pushed in `16f995e`; additive migration `0002_auth_security`, Argon2id/legacy upgrade, revocable sessions, rotating HttpOnly refresh cookie, email verification/recovery, rate limits, origin checks, production configuration validation, in-memory-only access tokens and role-aware UI.
- **Phase 2 customer commerce:** implemented and pushed in `f40dae1`; additive migration `0003_customer_commerce`, API-backed catalog, persistent customer cart, idempotent checkout, conditional inventory handling, ownership-scoped orders, signed referral continuity and responsive shop UI.
- **Phase 3 payment options/order lifecycle:** implemented in the current milestone; migration `0004_payment_options`, backend-only no-money Demo Payment, COD unpaid/fulfillment/administrator collection, disabled Online Payment, payment-attempt history, admin order management, audit records, demo-reward non-payability and removal of legacy guest simulator. See `docs/PAYMENT_OPTIONS.md` and `IMPLEMENTATION_STATUS.md` for verified test results and limitations.
- **Phase 4 (implemented on the current development branch; verified in SQLite/local test environments):** referral attribution and conversion tracking. Reuses existing Referral/Application and commerce/payment records; attribution rules and verification evidence are in `docs/referral-attribution.md`, `docs/REFERRAL_ATTRIBUTION_AUDIT.md`, and `IMPLEMENTATION_STATUS.md`. PostgreSQL migration/concurrency, browser E2E, privacy/legal review, and paid-order refund workflow remain release follow-ups. No production-ready claim is made.
- **Phase 6 (implemented on the current branch; local verification passed):** campaign management and trusted brand/admin analytics. Backend 53 tests and frontend 32 tests pass; lint/build, SQLite migration coverage, compileall and diff checks passed. Audit, definitions, results and limitations are recorded in `docs/PHASE_6_ANALYTICS_AUDIT.md` and `docs/PHASE_6_ANALYTICS.md`. PostgreSQL and browser E2E remain unverified.
- **Phase 7 (implemented on the current branch; local verification passed):** secure platform administration, session-revoking restrictions, manual verification and campaign moderation, human risk investigation, disputes with append-only event history, immutable admin audit events and operations UI. Backend 57 tests and frontend 35 tests pass; SQLite migration and local quality checks passed. PostgreSQL, browser E2E and production readiness remain unverified; see `docs/PHASE_7_ADMIN_AUDIT.md` and `docs/PHASE_7_ADMIN.md`.
- **Phase 8 (implemented locally; verification passed):** recipient-scoped notifications/preferences, encrypted retryable SQL email outbox, separate worker, transactional business/security event integration, authenticated inbox/settings APIs and admin delivery monitoring. SMTP inbox receipt, Docker Compose startup, PostgreSQL, browser E2E, multi-worker concurrency and production readiness remain unverified. Audit and implementation records: `docs/PHASE_8_NOTIFICATIONS_AUDIT.md` and `docs/PHASE_8_NOTIFICATIONS.md`.
- **Phase 9 (local system-wide QA completed):** backend **68 passed**, frontend **38 passed**, lint/build (includes TypeScript `tsc -b`), compileall, diff check, npm audit and copied-SQLite migration/integrity checks passed. Fixed mixed-brand order visibility, suspended-brand discovery/purchase eligibility and concurrent refresh rotation; a potential concurrent last-admin suspension risk was hardened but not independently race-tested. PostgreSQL, browser E2E, Python audit/SAST tools, multi-worker/load testing, external integrations, independent penetration testing and production readiness remain unverified. See `docs/PHASE_9_QA_AUDIT.md` and `docs/PHASE_9_TEST_RESULTS.md`.
