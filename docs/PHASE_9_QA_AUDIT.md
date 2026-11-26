# Phase 9 — System-wide QA audit

**Status:** local QA pass completed with documented limitations; not a production-readiness or independent penetration-test claim.
**Date:** 2026-11-25 (UTC)
**Branch:** `arena/e6c9b4f7-crownd-2-0`

## Scope and method

Phase 9 is verification and defect correction, not a feature-development phase. The review covered the four application roles (customer, creator, brand, administrator), resource ownership and sensitive data boundaries, session lifecycle, catalog/cart/checkout/order visibility, inventory/payment lifecycle, attribution/reward and ledger behavior, campaign/admin/risk/dispute operations, analytics, notification/outbox paths, schema/migrations, validation, frontend tests/build, and available concurrency behavior. Work used the repository's existing API, SQLite test fixtures, component tests, and temporary database copy; no external service credentials or live-money paths were exercised.

Evidence is separated into (a) executed automated tests/commands, (b) focused code review, and (c) unavailable environment-dependent checks. The full backend and frontend suites were rerun after the final code changes. Specific security and commerce regressions received targeted tests. A shared-file SQLite concurrency test provides only a narrow local race check; it is not a PostgreSQL, multi-process, load, or production concurrency certification.

## Defects, reproduction, fixes, regression evidence

### 1. Mixed-brand orders were not visible to every participating brand

- **Reproduction/root cause:** a customer checked out a mixed-brand cart. Brand order visibility was effectively tied to the order-level referral/brand association instead of the participating order lines, so one participating brand could miss its own order.
- **Fix/regression:** adjusted brand-scoped order access to derive visibility from the brand's own order items; expanded `test_phase5_mixed_cart_creates_idempotent_item_attributed_rewards_for_multiple_creators` to verify both participating brands see the order and a third unrelated brand does not.
- **Verification:** regression passed in the focused run and again in the full backend suite.

### 2. Suspended brands' published campaigns and products remained discoverable/purchasable

- **Reproduction/root cause:** suspending a seller did not consistently participate in public campaign/product eligibility; existing carts could also retain a product after suspension. Account lifecycle changed seller state, but several discovery and commerce queries checked only product/campaign state.
- **Fix/regression:** public campaign and product listing/detail/category/brand discovery, referral eligibility/application, cart availability/mutation, checkout validation, and stock decrement now require an active brand account of the expected role. A regression creates and publishes a campaign, adds a product to a cart, suspends the brand, then checks public visibility, the pre-existing cart, add/update, and checkout. It also asserts no order was created and stock was unchanged.
- **Verification:** focused suspended-brand and mixed-brand tests passed; the suspended-brand scenario passed in the full backend suite. The stock/order assertions are part of the test.

### 3. Concurrent refresh requests could both rotate the same refresh secret

- **Reproduction/root cause:** two synchronized requests were made to verify the same refresh secret before either persisted its rotation. Before the fix, both returned `200` and the session remained unrevoked; the read-then-write rotation had no conditional persistence guard.
- **Fix/regression:** refresh rotation now uses a conditional compare-and-swap update on the session ID, presented digest, active state, and expiry. A loser rereads state; if another request rotated the token, it records reuse, revokes the session, and returns `401`. `test_concurrent_refresh_requests_cannot_both_rotate_the_same_secret` synchronizes two requests after digest verification and asserts exactly one `200`, one `401`, and a revoked session.
- **Verification:** the regression passed on a temporary file-backed SQLite database and in the full backend suite. With reuse detection, the winning response's new token is revoked when the concurrent old token is subsequently recognized as reuse; clients must authenticate again. PostgreSQL behavior remains untested here.

### 4. Last-active-admin concurrent suspension risk (code-review hardening)

- **Finding type:** concurrency risk identified by code review, not a reproduced failure in this environment. Locking only the target admin could permit two administrators to race to suspend one another on a row-locking database.
- **Change:** admin suspension now locks the administrator cohort in stable ID order before reloading/checking the target, then continues the existing active-admin invariant and transactional session revocation.
- **Evidence/limit:** lifecycle and related regression tests pass in the backend suite. No dedicated two-admin race regression or PostgreSQL execution was available; do not treat the concurrency invariant as independently proven.

## Coverage inventory and evidence

| Area | Executed verification | Additional review / limitation |
|---|---|---|
| Roles and ownership | Backend tests cover role gates, private order ownership, admin operations, recipient-scoped notifications, and brand-owned campaign/order operations; full suite passed. | Reviewed sensitive route dependencies/ownership patterns. This is not an exhaustive endpoint-by-endpoint adversarial authorization campaign. |
| Authentication/session | Full backend suite; focused concurrent refresh test; existing tests cover refresh rotation/cookie attributes/revocation and auth workflows. | Email-provider delivery and production proxy/cookie configuration were not exercised. |
| Commerce, inventory, payment/COD | Full backend suite plus mixed-brand and suspended-seller regressions; suspended case asserts no order and unchanged inventory. | No live gateway, actual cash collection, refund/chargeback, or external settlement. |
| Attribution, conversions, rewards, ledger | Full backend suite includes multi-creator mixed cart/idempotency, reward state and immutable history coverage. | No production financial reconciliation, scheduled eligibility processing, or payout settlement exists/was tested. |
| Campaign/admin/risk/dispute/analytics | Full backend suite and existing frontend tests; code review of route/service boundaries and definitions. | No production-scale query/load benchmark; not every aggregate was independently recomputed from a large dataset. |
| Notifications/outbox | Full backend suite includes API/worker and migration coverage; frontend notification tests pass. | No external SMTP receipt; no competing workers or PostgreSQL queue claim test. SMTP acceptance would not establish inbox delivery. |
| Input validation | Prior focused validation in this Phase 9 work confirmed Pydantic rejects NaN/Infinity product prices, campaign reward rate, and budget. Full suite also passed. | No general-purpose fuzzing or external SAST run. |
| Frontend | 38 Vitest tests; ESLint; production build (includes `tsc -b`) all passed. | Browser-level E2E and accessibility automation not run; chart zero-size jsdom warnings remain. |
| Migrations/database | Copied the local SQLite database to `/tmp`, upgraded the copy from `0005_referral_attribution` through `0009_notifications`; migration head, SQLite integrity and foreign-key checks passed. | Original working DB was not upgraded. SQLite results do not prove PostgreSQL behavior. |
| Repository hygiene | Targeted tracked-source secret/debug-pattern grep returned no matches; `git diff --check` passed. `npm audit --audit-level=high` reported 0 vulnerabilities. | `pip-audit` and Bandit are not installed; the grep is not a complete secret scanner. |

## Migration and data integrity checks

- `alembic current` on the pre-existing local database reported `0005_referral_attribution`; `alembic heads` reported the sole head `0009_notifications`. The actual local database was intentionally left unchanged.
- A disposable copy at `/tmp/crownd-phase9-validation.db` upgraded to `0009_notifications`. SQLite `integrity_check` returned `ok`; `foreign_key_check` returned no violations; 35 tables were present.
- Basic snapshot queries on that copied database found zero negative product stock, negative order amounts, nonpositive order-item quantities, missing customer emails on orders, conversions without orders, rewards without orders, or ledger references to absent rewards. The dataset is small (orders/conversions/rewards/ledger rows were empty), so these counts are a smoke check, not evidence of general financial reconciliation or production-data cleanliness.
- PostgreSQL binaries/services and Docker/Podman were unavailable. PostgreSQL migration, native constraint semantics, row-locking, query plans, and production transaction behavior remain unverified.

## Non-goals and unresolved risk

No independent security professional penetration test, formal privacy/legal review, production readiness review, genuine payments/refunds, actual payout settlement, browser E2E, PostgreSQL integration, worker multi-process concurrency/load test, or external email-delivery verification was performed. Dependency vulnerability coverage is limited to npm audit; Python audit tools were absent. Findings from focused checks should not be generalized into a claim that all routes or state transitions are defect-free.

Detailed commands, run outcomes, and unavailable checks are in [`PHASE_9_TEST_RESULTS.md`](PHASE_9_TEST_RESULTS.md). Prior phase scope and known product gaps remain in [`IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md) and [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md).
