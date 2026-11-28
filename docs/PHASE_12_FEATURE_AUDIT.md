# Phase 12 — Product feature audit

**Audit date:** 2026-11-25
**Branch / starting revision:** `arena/e6c9b4f7-crownd-2-0` / `3f8ae348d16ed885bb4c9c1e163c63ed4da711d1` (branch base `67e80eb50c04fcfb3d4e654e12e50dd0cc8ff516`)
**Scope:** evidence-based review of the existing CROWND 2.0 application. This is a completion/repair audit, not a redesign or a proposal to add real payment rails.

## Completion estimate

**Estimated Phase 12 completion: 80%** (engineering estimate, not a test-derived KPI). Local code audit/repairs and the defined high-priority application workflows are substantially complete and all local automated suites pass. Remaining 20% reflects unclosed product scope (including messaging/invitations/evidence/address book), breadth of independent security/accessibility review, and external runtime acceptance. This is not production readiness: PostgreSQL migration/concurrency, browser E2E, SMTP, backup/restore, deployment and production smoke checks remain unverified, including P0 operational gates.

## Method and classification

Reviewed FastAPI v1 route handlers and service modules, SQLAlchemy entities and Alembic revisions, frontend route guards/navigation/API bindings/pages/components, existing tests and the prior Phase 5–11 audit/validation documents. Baseline tests were run before Phase 12 edits: backend **74 passed**; frontend **38 passed**, lint passed, and the TypeScript/Vite production build passed. These are local SQLite/jsdom/build results, not external infrastructure or browser E2E results.

- **COMPLETE** — primary workflow is connected end-to-end for the implemented scope and evidence exists.
- **PARTIAL** — useful implementation exists, but a notable workflow gap remains.
- **MISSING** — no product workflow exists in the reviewed tree.
- **BROKEN** — a confirmed defect prevents or corrupts an otherwise implemented workflow.
- **PLACEHOLDER** — UI/content implies functionality or data that is static, illustrative without adequate disclosure, or a dead-end action.
- **DISCONNECTED** — related UI/API/domain exists but the user-facing workflow does not join them.
- **UNVERIFIED** — source/local tests do not establish behavior in the required external runtime/provider/browser environment.

Priority is based on user/security/financial impact: **P0** release/security/data integrity blocker; **P1** important workflow or trust issue; **P2** meaningful product completeness/usability gap; **P3** polish or future capability. Status labels describe observed product scope, not an assertion that every test case was exhaustively fuzzed.

## Module findings

| Module | Status | Priority | Evidence and outcome |
|---|---|---:|---|
| Authentication, verification, recovery, sessions | COMPLETE | P1 | `backend/app/api/v1/auth.py`, `backend/app/services/auth.py`, auth schemas and `AuthFlows.tsx` provide verified signup, Argon2id/legacy upgrade, verification/reset one-use tokens, rotating HttpOnly refresh, revocation and rate/origin controls. Existing auth tests cover invalid credentials, unverified sign-in, expiry/replay and session revocation. SMTP delivery remains UNVERIFIED (see operations). |
| Account/profile management | COMPLETE for editable role fields | P1 | Strict `/me/profile` plus `/creators/me`, creator/brand/customer/admin role-aware update fields, uniqueness, field bounds, HTTPS website check, audit event, profile UI and tests. Email update, customer saved-address book and external verification remain outside scope. |
| Customer product discovery | COMPLETE | P2 | `/products`, categories/brands, filters, pagination, product detail and cart/checkout UI use real data. `CustomerCommerce.tsx` tests cover discovery/detail/cart flows. |
| Customer cart, checkout, orders | COMPLETE (simulated scope) | P1 | Persisted cart, server Decimal recomputation, stock reservation, idempotency, address snapshots, ownership-scoped order views, cancellation/inventory restoration and admin fulfillment are implemented/tested. Only **simulated demo payment and COD** are supported; online is rejected. No real gateway is in scope. PostgreSQL concurrency is UNVERIFIED. |
| Brand product catalog management | COMPLETE (local CRUD/soft status) | P2 | Owner-scoped paginated list, validated create/update/inventory/status endpoints, editor and admin moderation now exist. Historical rows are never hard-deleted; linked published campaigns must be paused before deactivation. No schema change was needed. |
| Creator discovery / brand invitations | DISCONNECTED | P2 | `/creators` is authenticated and returns creator profile values; the invitation entity/workflow does not exist. Phase 12 removed the misleading Invite toast/button. Discovery now shows creator-provided bio and labels audience figures as profile-reported, not externally verified. |
| Campaign authoring, ownership, lifecycle | PARTIAL | P1 | Brand campaign workspace supports create/edit/status transitions, product ownership validation, pagination and metrics; creator applications and referral eligibility connect to active campaigns. The generic `/campaigns` UI does not expose complete application context. Phase 12 removed fake campaign fallback and now shows real loading/error/empty states; the brand campaign workspace remains the complete authoring surface. |
| Applications and collaboration | PARTIAL | P1 | Creator apply, brand/admin review, ownership scoping, duplicate DB constraint, referral issuance and notifications exist. Phase 12 repaired unrestricted request dictionaries and repeated/invalid state-change side effects with strict bounded request models, duplicate submission conflict handling, row-locked status review, explicit transitions and same-state no-op behavior. The broader partnership/messaging workflow remains PARTIAL. |
| Referral links / attribution | COMPLETE (local scope) | P1 | Accepted applications gate referral links; signed attribution, product eligibility, click/activity tracking, conversions, self-referral handling and admin review are implemented in `routes.py`, `commerce.py`, referral/conversion services, and covered by commerce/analytics tests. Attribution persistence and multi-process DB behavior remain UNVERIFIED on PostgreSQL. |
| Conversions, COD/demo lifecycle, rewards and ledger | COMPLETE (no transfer) | P1 | Conversion state follows payment/order lifecycle; COD rewards await collection/hold; demo rewards are non-payable; admin decisions append events/ledger and simulations explicitly transfer no money. Tests cover reward calculation, idempotency, transitions, reversal and demo disclosures. Actual payouts/refunds are MISSING by design, not a Phase 12 addition. |
| Brand/admin analytics | PARTIAL | P2 | Server-side aggregate metrics, campaign/creator/product reports, period filtering, CSV export and privacy exclusion exist with analytics tests. Legacy generic analytics/dashboard panels are less complete than `CampaignIntelligence.tsx`; ROI is explicitly unavailable absent cost records. True financial ROI and external analytics are not available. |
| Admin operations and moderation | COMPLETE (local scope) | P1 | Admin-only user lifecycle, last-admin guard, verification/moderation, orders, rewards, referrals, disputes, audit history and redacted delivery telemetry are implemented with dedicated tests. Concurrent DB row-lock behavior is UNVERIFIED on PostgreSQL. |
| Trust and risk | PARTIAL | P1 | Referral risk flags are explainable and human-reviewed; creator profiles retain internal crown/trust score fields, but no external social-account verification or fabricated-metric detection provider is connected. Score provenance/calibration is not independently evidenced; Phase 12 hides the unexplained scores in creator discovery and labels visible audience figures as creator-reported. |
| Disputes | PARTIAL (order issue intake + admin resolution) | P2 | Customer/creator/brand can open a case only for an order they own/participated in; reporter-scoped history, duplicate-open guard, admin inbox notification, typed admin resolution and reporter status notification are covered. Evidence uploads and financial changes remain absent. |
| Notifications | COMPLETE (local scope) | P2 | Recipient-scoped inbox, preferences, transactional event keys, encrypted SQL outbox and admin redacted monitor are implemented and tested. SMTP provider acceptance/inbox receipt and worker behavior under PostgreSQL/multiple workers remain UNVERIFIED. |
| Messaging / campaign conversations | MISSING | P2 | No conversation model/API exists. Phase 12 removed the sidebar entry and replaced the direct route with an explicit unavailable message; no user can be led to believe that conversations are stored or sent. |
| Support/help | PLACEHOLDER | P3 | No support destination or ticket integration exists. Phase 12 removed the dead-end action and leaves the sidebar support contact clearly unavailable. |
| Dashboard / navigation / route behavior | PARTIAL | P1 | `App.tsx` initially used hard-coded campaign examples, a fixed date, a non-functional range control, a toast-only activity action, and zero defaults on failed requests. Phase 12 removed these false states; recent activity now uses the notification API with real action paths, the chart amount matches the paid-order series, and query loading/error/empty cases are explicit. Dashboard range customization and richer per-role dashboards remain incomplete. Route role checks in `routes/access.ts` exist and have unit tests; server authorization remains the actual security boundary. |
| Migrations and schema | COMPLETE (SQLite-tested) / UNVERIFIED (PostgreSQL) | P1 | Nine additive Alembic revisions end at `0009_notifications`; models have domain constraints and idempotency/ownership keys. Fresh/copy SQLite upgrade evidence exists. Phase 12 found no need for a schema migration. PostgreSQL migration/locking/backup-restore are not validated. |
| Test coverage and regression quality | PARTIAL | P1 | Baseline backend 74 tests; frontend 38 across nine test files. Tests cover major workflows but there is no Playwright browser E2E, full endpoint fuzzing, independent penetration review, or PostgreSQL integration/concurrency execution. New Phase 12 tests target profile/application and product ownership boundaries, creator/application UI permissions, user disputes, product moderation and dashboard behavior. |
| External integrations and operations | UNVERIFIED / PARTIAL | P0 release gate | Real SMTP, external payment/payout, production DB, backup/restore, Docker/Compose, deployment, and production smoke checks are not validated. Existing Phase 11 documents record blockers. Do not use the connected Supabase project; the user chose a different isolated PostgreSQL target and no endpoint was supplied. Docker installation was deferred. |

## Confirmed issues selected for Phase 12 implementation

1. **P1 — profile/API validation (FIXED):** replaced open dictionaries with strict role-aware schemas and profile UI; tests cover invalid ranges, role-field boundaries, uniqueness and audit behavior.
2. **P1 — application payload/state handling (FIXED):** strict bounded schemas, duplicate conflict, row-lock where supported, explicit transitions and no-op repeated review are tested.
3. **P2 — product ownership and inventory UI (PARTIALLY FIXED):** brand create/edit/stock/soft status plus owner scoping and admin moderation work locally. Hard deletion is intentionally disallowed; full catalog pagination/actions and PostgreSQL verification remain.
4. **P1 — dashboard truthfulness:** remove sample campaign fallback, static date, fake zero-on-error interpretation, and no-op controls; show backend loading/error/empty states and make real navigation actions.

No database/schema changes were required for this continuation. Payment scope stays demo simulation plus COD only. A conversations/messaging feature, support system, invitation workflow, real gateways, payout transfers and external account verification are not being added as part of these repairs.

## Residual prioritized work

- **P0:** complete Phase 11 using an approved isolated PostgreSQL and browser/Docker-capable environment; run backup/restore, worker/SMTP acceptance, migration/concurrency and staged deployment/smoke checks. No local code change can substitute for these checks.
- **P1:** expand endpoint-level malformed-input/authorization review, PostgreSQL race tests, and accessibility/security review; verify any creator trust-score/metrics source before presenting it as externally verified.
- **P2:** creator invitations and messaging/conversation system still require product acceptance criteria; customer saved-address book and evidence attachments are not implemented.
- **P3:** connect a real support destination and improve dashboard range selection only when corresponding backend range semantics are specified.


## Phase 12 implementation verification update

Completion remains an estimated **80%**: local implementation and regression verification are strong, while the residual feature scope and Phase 11 external validation prevent closure or production-readiness claims.

Continuation batch verification: backend **81 passed**; frontend **54 passed** across 14 files; lint, TypeScript/Vite build, compileall, frontend and Python dependency audits and diff checks passed. Phase 12 now includes typed profile/application input, replay-safe review actions, accurate dashboard/discovery loading/error/empty states, a notification-backed recent-activity panel, role guard for Applications, removed dead-end messaging/invitation actions, explicit disclosure for illustrative marketing examples and creator-reported metrics, and an owner-scoped brand product catalog with truthful inventory entry. Full details and remaining work are in [`PHASE_12_IMPLEMENTATION_LOG.md`](PHASE_12_IMPLEMENTATION_LOG.md). PostgreSQL/production operations and browser E2E remain unverified as described in Phase 11 records.

## Continuation inventory — module-by-module feature status

Statuses below refer to the behavior in the current local tree and the tests named, not production deployment. **COMPLETE** means the available local workflow is connected and tested for its stated scope; real payments, SMTP inbox receipt, PostgreSQL, and browser E2E are not implied.

### A. Customer module

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Registration, verified login, logout/session revocation | COMPLETE (local) | `auth.py`, `AuthFlows.tsx`; `test_registration_verification_required_and_passwords_are_argon2id`, logout/refresh tests. | Actual SMTP delivery remains UNVERIFIED (P0 operations). |
| Customer account profile | COMPLETE (basic) | New role-aware `PUT /me/profile`, `AccountProfile.tsx`; `test_role_aware_account_profile_updates_are_validated_and_audited`, `AccountProfile.test.tsx`. | Display name and creator/brand profile fields are editable; verified email and a customer address book are not implemented (P2). |
| Product search, filters, pages, detail | COMPLETE (local) | `/products` and `CustomerCommerce.tsx`; `test_discovery_search_filters_sort_pagination_and_details`, frontend shop/detail tests. | Browser E2E and live image hosting UNVERIFIED. |
| Persistent cart and quantity changes | COMPLETE (local) | Authenticated cart endpoints and query refresh; `test_authenticated_cart_persists_recalculates_and_enforces_ownership`, frontend cart test. | PostgreSQL concurrent DB behavior UNVERIFIED. |
| Checkout/address validation, order persistence, COD/demo | COMPLETE (simulated) | `CheckoutRequest`, checkout transaction and payment services; checkout/COD/demo tests in `test_commerce.py` and `CustomerCommerce.test.tsx`. | Demo is not a real charge; COD collection is recorded manually; no gateway (P0/P1 scope). |
| History/details/eligible cancellation/restock | COMPLETE (local) | Owned order views and `_cancel_order_record`; `test_inventory_race_guard_unavailable_cart_and_cancel_restores_stock`, frontend order-detail/cancel tests. | Paid-order refund/reversal is MISSING; no refund provider or admin workflow (P1 financial scope). |
| Referral attribution and order notification | COMPLETE (local) | Signed attribution state, order events, recipient-scoped notifications; mixed-cart/last-valid-touch/COD tests. | Consent/retention legal review and cross-process PostgreSQL behavior UNVERIFIED (P0/P1). |

### B. Creator module

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Registration and default creator profile | COMPLETE (local) | Auth registration creates profile; auth/workflow tests. | Email provider acceptance/inbox delivery UNVERIFIED. |
| Profile edit and validation | COMPLETE (local) | `PUT /me/profile` and legacy `/creators/me`, strict typed values, unique username, audit; workflow tests and `AccountProfile.test.tsx`. | External account/metric verification MISSING; values explicitly self-reported. |
| Campaign discovery and matching eligibility | PARTIAL | Public discovery filters status/date/visibility; `/ai/matches` and eligible referral campaigns require role/participation. | Matching remains deterministic heuristic; no third-party trust verification. Some discovery is capped at 30 without a total count (P2). |
| Apply, status and approved participation | COMPLETE (local) | Strict application schema, creator-visible status, brand/admin-only review controls; duplicate and transition tests plus `App.applications.test.tsx`. | Collaboration brief delivery/task tracking and messaging are MISSING (P2). |
| Referral generation/persistence, attribution, conversion lifecycle | COMPLETE (local) | Accepted-application gating, signed cookie state, conversion unique per order; workflow and commerce referral tests. | PostgreSQL race tests and browser cookie continuity UNVERIFIED (P1). |
| Creator analytics, rewards and ledger | COMPLETE (local scope) | Creator analytics/conversion/reward/ledger routes and `Rewards.tsx`; reward-engine and referral tests. | Date windows are limited to supported API parameters; no payout transfer; financial/tax settlement MISSING by design. |
| Notifications | COMPLETE (local queue) | Event-key deduplication, inbox/preferences/outbox; notification tests. | SMTP acceptance and multi-worker delivery UNVERIFIED. |

### C. Brand module

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Registration/profile/manual verification | COMPLETE (local) | Brand registration, role-aware profile update, audited admin verification; workflow/admin tests. | Verification is manual, not an external identity check. |
| Product CRUD/inventory/visibility | PARTIAL (improved) | Create, owner-only update/stock/sale/image/specification fields, soft deactivation/reactivation; paginated `/brand/products`; owner and audit tests; brand UI now edits and toggles status. | No hard delete intentionally (preserves order/referral history); cannot deactivate while a linked campaign is published. Full live browser test absent (P2). |
| Campaign CRUD/lifecycle and eligible products | COMPLETE (local scope) | Brand-scoped list/detail/edit, dates, structured goals/product ownership, status transitions; `test_campaign_management_lifecycle_and_brand_ownership`. | Budget is a ceiling, not a spend ledger; no creator conversation/tasks. |
| Creator application review and referrals | COMPLETE (local) | Ownership-scoped application list/review and accepted-referral creation; `test_application_payload_validation_owner_checks_and_idempotent_review`. | Invite-before-application is not implemented. |
| Analytics/conversion reports/CSV/reward rules | COMPLETE (local scope) | `analytics.py`, `services/analytics.py`, `CampaignIntelligence.tsx`; `test_brand_campaign_analytics_uses_item_attribution_and_separates_payment_states`, CSV privacy/formula tests. | ROI/spend is unavailable; custom date limit and order-created cohort semantics documented in `PHASE_6_ANALYTICS.md`. |
| Brand data isolation | COMPLETE (SQLite tests) | Route ownership checks and owner-scoped product list/update; commerce and campaign isolation regressions. | PostgreSQL locking/concurrency UNVERIFIED. |

### D. Product and inventory

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Create, update, status/deactivation, ownership | COMPLETE (local create/update/soft status) | `ProductCreate`, `ProductUpdate`, brand status route and admin moderation; `test_brand_can_update_and_deactivate_only_owned_products_without_deleting_history`. | No destructive delete; this is intentional financial-history preservation. |
| Stock validation/reservation/deduction/restore | COMPLETE (SQLite local) | Decimal totals and conditional inventory decrement; cancellation/demo-failure restore tests. | No PostgreSQL race/oversell load test (P0 verification). |
| Product visibility and admin moderation | COMPLETE (local) | Public discovery filters active products; admin reason/typed-confirmation action; `test_admin_product_moderation_is_paginated_audited_and_preserves_product_record`, AdminOperations UI test. | Published campaigns must be paused before product deactivation; external moderation appeals absent. |

### E. Campaign system

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Create/edit/activate/pause/complete/cancel | COMPLETE (local API/UI) | Brand campaign workspace and status transition API/tests. | External spend/budget settlement is not modeled. |
| Eligibility, dates, visibility and products | COMPLETE (local) | Campaign date/status filters; hidden/unlisted and product ownership tests. | Platform-specific creator requirements are descriptive fields, not automatically evaluated. |
| Applications/review/referrals | COMPLETE (local) | See creator/brand evidence above; unique application constraint and allowed state machine. | No team messaging or deliverable workflow (P2). |
| Reward commission/rules and analytics | COMPLETE (local scope) | Snapshotted reward rules and item-attributed campaign reports; phase 5/6 tests/docs. | No actual payment or payout integration. |

### F. Referral and conversion

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Code/link generation and persistence | COMPLETE (local) | Eligible accepted creators, persisted codes, activation/revocation; referral-link API tests. | No external link shortener. |
| Signed attribution, first/last touch and expiry | COMPLETE (local) | `docs/referral-attribution.md`; cookie signing, hashed visitor token, last-valid-touch replacement and configured window; tests for valid/invalid/direct visits. | Browser E2E, consent policy and PostgreSQL multi-worker persistence UNVERIFIED. |
| Product/campaign eligibility and mixed carts | COMPLETE (local) | Checkout rechecks brand/campaign/product; eligible item lines attributed; mixed cart test. | Cannot claim third-party social identity verification. |
| Duplicate conversion prevention and lifecycle | COMPLETE (local) | Unique order conversion, transactional creation/events; demo/COD/cancellation/reversal tests. | Refund provider workflow absent; post-paid reversal remains restricted. |
| Analytics accuracy | COMPLETE (local definitions) | Attribution by order-item snapshots and separate pending/confirmed/demo/COD states; `PHASE_6_ANALYTICS.md`. | Some legacy summary endpoints are less complete than item-based reports; consumers should use the documented analytics APIs. |

### G. Order management

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Creation/idempotency/ownership/brand/admin access | COMPLETE (local) | Checkout key uniqueness, snapshots, `_can_view_order`, admin filters; commerce tests. | PostgreSQL unique races UNVERIFIED. |
| Status/payment/COD/demo lifecycle | COMPLETE (simulated/local) | Admin fulfillment, COD collection only after delivery, demo outcomes; tests verify no premature COD reward. | Online gateway is unavailable; demo payment makes no charge. |
| Cancellation/restock | COMPLETE for eligible unpaid orders | Idempotent status transition and stock restoration; cancellation tests. | Paid-order refunds/restocking and dispute-driven adjustments are MISSING (P1); no financial records are deleted. |

### H. Reward and financial ledger

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Decimal calculation, rule snapshots and idempotency | COMPLETE (local) | `rewards_engine.py`, unique conversion/order reward keys, Decimal/HALF_UP tests and rule-precedence tests. | PostgreSQL concurrency UNVERIFIED. |
| COD qualification, demo non-payability and lifecycle | COMPLETE (local scope) | Rewards remain pending collection until admin records delivered COD cash; demo rewards cannot be paid; commerce/reward tests. | No real transfer/payout. |
| Ledger integrity and audit immutability | COMPLETE (SQLite + ORM guards) | Append-only event/ledger and DB migration triggers, admin tests. | Trigger behavior on a live PostgreSQL target not run. |
| Payout simulation/disputes | PARTIAL | Admin simulated payout is clearly disclosed; dispute resolution is now user-submittable for an owned order and admin-reviewed, without financial mutation. | Simulation is not settlement; disputes do not issue refunds, change rewards, or support evidence attachments. |

### I. Analytics

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Creator/brand/campaign/product/conversion/reward/admin reports | COMPLETE (local scope) | Database aggregate endpoints/UI in analytics and referral modules; phase tests/docs. | Customer-specific behavior analytics are not a product feature; only own orders/paid-order series are exposed. |
| Date ranges/filtering/pagination/CSV | COMPLETE in supported report surfaces | `CampaignIntelligence.tsx`, brand export, creator days, paginated creator conversions/admin lists. | Creator/admin CSV breadth differs; legacy dashboards use fixed seven-month series. |
| Metric truth/definitions/privacy | COMPLETE (documented local definitions) | No fabricated dashboard fallback; marketing samples labeled; `PHASE_6_ANALYTICS.md` documents paid revenue, demo, COD, reward states, non-ROI ratios, cohort time, privacy. | External event delivery and independent audit remain unverified; actual cost/ROI not available. |

### J. Admin

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| User suspension/reactivation and verification | COMPLETE (local) | Role-gated reasoned actions, session revocation, last-admin safety, typed confirmations; admin tests/UI. | Arbitrary role reassignment is intentionally unavailable; promotion requires a separate secure operation. |
| Campaign/product moderation | COMPLETE (local) | Campaign moderation plus new paginated product queue and audited activation/deactivation with reason/confirmation; backend/frontend tests. | No moderation appeal/evidence workflow. |
| Order/reward/risk/dispute/audit oversight | COMPLETE (local scope) | Admin dashboards and append-only trails; admin/rewards/commerce tests. | PostgreSQL concurrent control paths UNVERIFIED. |
| Notifications operations | COMPLETE (local monitoring) | Redacted delivery monitor, queue summary; notification tests. | Provider inbox acceptance and worker-in-production UNVERIFIED. |

### K. Trust, risk and disputes

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Risk flags/review | COMPLETE (human review only) | Explainable referral/self-referral flags; reasoned admin review is audited; no automatic penalty. | No social verification or model calibration provider. |
| User reports/disputes | PARTIAL → user intake added | New `POST/GET /disputes` lets customer/creator/brand report only an order they own/participate in, prevents a duplicate open case by the same reporter/order, notifies active admins, and exposes case history; order detail form added. | Intake currently links orders only; evidence upload, other conversion/reward-only references and a customer-facing resolution center are future work. |
| Admin resolution and financial protection | COMPLETE (local) | Existing reason/typed-confirmation transition creates append-only events and now notifies the reporter; dispute tests assert order/payment amount/state unchanged. | No refund/reward modification is performed by design; decisions stay investigation-only. |

### L. Notifications

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Creation, inbox, read/unread, preferences, event idempotency | COMPLETE (local) | Recipient-scoped APIs, safe paths, event keys; `test_inbox_pagination_ownership_unread_and_safe_relative_actions`, preference tests. | No in-app browser E2E. |
| Email outbox, retry, failure handling | COMPLETE in local worker code | Encrypted payload, bounded retry/backoff and redacted error code; worker transient/permanent tests. | Real SMTP/provider acceptance and Compose deployment UNVERIFIED (P0). |
| Dispute and business event triggers | COMPLETE (local) | Order/campaign/application/reward/auth triggers and new dispute reporter/admin notifications. | Cross-worker/PostgreSQL delivery semantics UNVERIFIED. |

### M. Frontend/backend integration

| Feature | Status | Evidence / implementation | Remaining limitation / priority |
|---|---|---|---|
| Auth/shop/cart/checkout/orders/referrals/rewards/analytics/notifications/admin | COMPLETE for tested local journeys | React Query API bindings and component tests; workflows listed above. | Browser E2E and external email/payment endpoints unavailable. |
| Creator and account profile forms | COMPLETE (local) | New `/profile` route, role-aware fields, GET `/auth/me`, PUT `/me/profile`, state update and success/error tests. | Email changes/address-book functionality absent. |
| Brand product create/edit/inventory/status and admin moderation | COMPLETE (local) | Owner-scoped query, update/deactivation endpoints and refreshed queries; owner/admin tests and UI action tests. | No hard delete; active campaign coupling intentionally blocks deactivation. |
| Application list actions and creator permissions | COMPLETE (local) | Creator status view, brand/admin review-only actions, loading/error/retry; frontend access tests. | Collaboration messaging remains absent. |
| Creator discovery/search | PARTIAL (improved) | Search includes saved name/username/niche/platform; loading/error/retry and self-reported metrics; frontend states tested. | Endpoint remains capped at 30; no filter facets/page metadata. |
| Dead/placeholder controls and public pages | PARTIAL | Search button now honestly navigates to campaign discovery; “how it works” scrolls to the actual section; message/support/invite actions no longer imply unavailable operations. | `/pricing` currently resolves to the landing page, not a pricing model; public pricing/marketing routes are informational placeholders (P3). |

## Current implementation batch and root causes

- **P1 account/profile disconnect:** profile APIs existed but there was no profile route and customer/brand fields lacked a role-aware edit path. Added strict `/me/profile`, profile screen, self/role checks, URL validation and audit events. No schema change.
- **P2 brand catalog gaps:** brand list read public discovery, create silently supplied fixed stock, and no owner update/status endpoints existed. Added authenticated listing/update/status APIs, editor, stock and availability controls. Soft status preserves financial references; no hard delete is offered.
- **P1 application action mismatch:** creator rows displayed brand review buttons that inevitably failed server authorization. Moved actions behind brand/admin role check and added status/error/loading behavior.
- **P2 discovery and search mismatch:** UI advertised platform search while API `q` ignored platform; added platform to server search and true loading/error/retry states.
- **P2 admin product moderation gap:** no admin product queue/action existed. Added paginated list and audited reason/confirmation workflow; active campaign-linked items cannot be deactivated.
- **P2 dispute submission gap:** disputes were admin-created only. Added role/ownership-scoped order issue intake and reporter history; status changes notify the reporter. No financial record or product/order state is changed.

## Verification snapshot and remaining risks

Current full snapshot: backend 81 passed; frontend 54 passed across 14 files; frontend lint/build, full `npm audit`, and `pip-audit -r requirements.txt` passed; both dependency audits reported zero known vulnerabilities. PostgreSQL/browser/production checks remain unverified. No migration was necessary: existing `AdminDispute.opened_by` and `AdminAuditEvent` support user-originated order disputes and account updates. Current Alembic head remains `0009_notifications`.
