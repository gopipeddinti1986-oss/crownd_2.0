# Phase 13 — Implementation log

**Status:** In progress; implemented locally, not complete.  
**Branch:** `arena/e6c9b4f7-crownd-2-0`  
**Database safety:** All test database use in this phase was disposable SQLite; the connected Supabase project and production data were not touched.

## Work performed

1. **Checkout reward snapshots and immutable order history**
   - Added nullable JSON `OrderItem.reward_snapshot`, `Reward.dispute_hold`, and `Reward.dispute_prior_status` with additive Alembic revision `0010_integration_snapshots` after `0009_notifications`.
   - Checkout captures the effective referral, creator, brand, campaign, product, rule/default terms, caps, currency and campaign budget for attributed items. COD collection uses and validates those frozen terms; legacy rows without a snapshot keep the prior path.
   - Added ORM rejection for order-item update/delete and DB triggers for SQLite/PostgreSQL. Historical rows are preserved; corrections/reversals remain append-only.

2. **Reward/dispute lifecycle**
   - Linked order/conversion/reward disputes hold associated non-demo rewards in review and produce deterministic reward events/notifications. Resolution releases the hold only when no other linked dispute remains, preserves risk/suspension review and leaves ledger history unchanged.
   - Explicitly flush dispute status before querying for remaining open disputes; this fixes stale-state release behavior with autoflush disabled.
   - Reward approval and payout simulation reject suspended creators.

3. **Commerce and campaign coordination**
   - Cart edit/remove/clear paths lock the cart before its items. Checkout locks cart items and products in stable product-ID order, conditionally decrements inventory, repeats the idempotency lookup after obtaining the cart lock, and safely recovers concurrent first-cart creation from the unique-user constraint.
   - Checkout, cancellation, COD collection, order status changes and campaign application/order events notify the involved customer, creator or brand using deterministic event keys where possible.
   - Campaign/application acceptance checks active campaign, brand and creator. Campaign publication validates explicitly selected products; campaign/product state changes and application/dispute reward coordination use row locks where applicable.

4. **Creator conversion and analytics consistency**
   - Creator conversion listing includes mixed-cart orders with creator-attributed order items and reports only the creator's own attributed amount/lines. Legacy conversions without item-level referral rows keep their stored payload.
   - Referral counters/creator analytics use item-level attribution; brand product filters allow historically attributed products without misrepresenting current eligibility.

5. **Regression tests**
   - Extended COD integration coverage: persisted checkout snapshot, campaign terms changed before collection, frozen-rate reward, dispute hold/release, unchanged ledger history.
   - Extended mixed-cart coverage: persisted rewards/ledger and each creator's scoped conversion amount/attribution lines.
   - Migration tests now assert `0010_integration_snapshots` as the head and verify columns and SQLite append-only triggers, including historical upgrade/re-upgrade paths.

## Verification executed

- `cd backend && ./.venv/bin/pytest -q` — **81 passed**, 1 warning, in 25.39s. The warning is upstream `StarletteDeprecationWarning` about `httpx` with `starlette.testclient`.
- From `backend/`, `python -m compileall -q app migrations tests` — passed after the final source edits.
- `git diff --check` — passed after the final source/docs edits.
- Credential-pattern scan over tracked diff and all three untracked deliverables — no obvious hard-coded credentials found.
- `cd backend && ./.venv/bin/alembic heads` — `0010_integration_snapshots (head)`.
- Migration tests run as part of the backend suite on temporary SQLite databases, including fresh/historical upgrades and downgrade/re-upgrade. No PostgreSQL migration test was run.
- No frontend tests, lint/build, live SMTP, worker multi-process, PostgreSQL, Docker/Compose, browser E2E, backup/restore, deployment or production smoke checks were run in this Phase 13 turn.

## Defects found while validating and fixed

- Account-lifecycle notification key referenced a nonexistent `User.updated_at`; changed to use the persisted admin audit event ID, and retained admin-audit reason/metadata.
- Existing migration tests still expected `0009_notifications` after upgrading to `head`; updated them for `0010_integration_snapshots`.
- COD dispute resolution queried before flushing the changed dispute status in autoflush-disabled sessions; added an explicit flush and asserted released persisted state.
- Mixed-cart creator analytics previously depended on the conversion's primary creator/referral and order-total amount; now derives creator-scoped lines and preserves legacy records without lines.

## Files changed

- Backend: `app/api/v1/admin.py`, `app/api/v1/analytics.py`, `app/api/v1/commerce.py`, `app/api/v1/campaigns.py`, `app/api/v1/routes.py`, `app/models/entities.py`, `app/services/rewards_engine.py`.
- Migration: `migrations/versions/0010_integration_snapshots.py`.
- Tests: `tests/test_commerce.py`, `tests/test_admin_migration.py`, `tests/test_campaign_migration.py`, `tests/test_notifications_migration.py`.
- Required project records: `docs/PHASE_13_INTEGRATION_AUDIT.md`, this log, `IMPLEMENTATION_STATUS.md`, and `docs/DEVELOPMENT_ROADMAP.md`.

## Remaining blockers and next checks

- No approved isolated PostgreSQL endpoint is available. Do not use connected Supabase. PostgreSQL locking, inventory races, simultaneous idempotency retries, campaign suspension races, migration DDL/trigger behavior and multi-worker notification idempotency remain unverified.
- Add synchronized multi-session integration tests against a disposable PostgreSQL database when a safe target is available; retain tests for persisted-state invariants.
- Re-run `compileall`, full backend tests, `git diff --check`, secret-pattern review and inspect the final diff. Run frontend regression checks if API response contract changes warrant it.
- Update this log with only actually executed results. No commit, push, migration against a shared DB, or Phase 13 completion claim is recorded here.
