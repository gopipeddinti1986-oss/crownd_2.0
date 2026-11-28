# Phase 13 — Implementation log

**Status:** In progress; local SQLite and frontend checks pass, PostgreSQL integration suite is prepared but skipped because no approved disposable instance is available.
**Branch:** `arena/e6c9b4f7-crownd-2-0`  
**Database safety:** Executed tests used disposable SQLite. The PostgreSQL suite is opt-in and scopes its schema in a database explicitly acknowledged as disposable. The connected Supabase project and production data were not accessed or modified.

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
   - Extended COD integration coverage: persisted checkout snapshot, campaign terms changed before collection, frozen-rate reward, dispute hold/release, unchanged ledger history. Added tampered-product snapshot test; COD collection flags the mismatch and creates no reward or ledger credit.
   - Extended mixed-cart coverage: persisted rewards/ledger and each creator's scoped conversion amount/attribution lines.
   - Added attribution-expiry/campaign-expiry coverage that verifies old conversions/rewards remain intact and expired attribution cannot create new ones.
   - Extended brand lifecycle coverage through reactivation; added creator suspension/reactivation coverage across sessions, referral use, new orders, notifications and retained historical conversion/reward rows.
   - Cancellation replay now asserts stock is not restored twice. Migration coverage removes the new columns from an 0009-shaped temporary SQLite DB, verifies 0010 adds them, then executes UPDATE/DELETE statements to prove SQLite triggers reject mutation.
   - Added opt-in PostgreSQL tests for actual 0009→0010 upgrade/downgrade/re-upgrade and trigger enforcement, transaction rollback, concurrent last-item checkout, concurrent cart creation + same-key attributed checkout, and concurrent overlapping disputes. These are **not executed** without an approved disposable PostgreSQL URL.
   - Finalization directly replays conversion creation with altered values and reward generation after COD collection, asserting the original conversion/reward and unchanged event, ledger, and notification counts.

## Verification executed (continuation)

- `cd backend && ./.venv/bin/pytest -q` — **84 passed, 4 skipped**, 1 warning, in 26.33s. Skips are the four explicit PostgreSQL-only tests in `tests/test_phase13_postgres.py`; they skip because no disposable DB URL/acknowledgment is configured. The warning is upstream `StarletteDeprecationWarning` about `httpx` with `starlette.testclient`.
- `cd backend && python -m compileall -q app migrations tests` — passed.
- `cd frontend && npm test -- --run` — **54 passed across 14 files**. Two existing Recharts zero-size warnings appear in jsdom chart tests.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed, including `tsc -b` and production Vite build.
- Migration tests ran on disposable temporary SQLite databases. The historical-path test removes the three 0010 columns before `upgrade head`, confirms column addition and proves SQLite triggers reject raw UPDATE/DELETE. The supported downgrade is deliberately non-destructive; columns/triggers persist and re-upgrade succeeds.
- `cd backend && ./.venv/bin/alembic heads` — `0010_integration_snapshots (head)`.
- Finalization re-ran the backend suite: **84 passed, 4 skipped** in 25.18s; the skips are the four opt-in PostgreSQL cases. `compileall` passed and Alembic head remained `0010_integration_snapshots`.
- Finalization also ran a fresh temporary SQLite online upgrade through `head`; `PRAGMA integrity_check` returned `ok` and the update/delete snapshot triggers were present. The temporary database was removed.
- Frontend was re-run during finalization: **54 passed across 14 files**; lint and `npm run build` (including `tsc -b`) passed. Two existing Recharts jsdom zero-size warnings remain.
- A non-required `alembic upgrade head --sql` probe failed at existing migration `0002_auth_security` because offline Alembic supplies a `MockConnection` that the migration calls `inspect()` on. Normal online fresh SQLite migration passed; offline SQL rendering is not claimed.
- No PostgreSQL test ran. No Docker/Compose, browser E2E, live SMTP acceptance, multi-worker runtime, backup/restore, deployment or production smoke checks ran.

## Defects found while validating and fixed

- Account-lifecycle notification key referenced a nonexistent `User.updated_at`; changed to use the persisted admin audit event ID, and retained admin-audit reason/metadata.
- Existing migration tests still expected `0009_notifications` after upgrading to `head`; updated them for `0010_integration_snapshots`.
- COD dispute resolution queried before flushing the changed dispute status in autoflush-disabled sessions; added an explicit flush and asserted released persisted state.
- Mixed-cart creator analytics previously depended on the conversion's primary creator/referral and order-total amount; now derives creator-scoped lines and preserves legacy records without lines.

## Files changed

- Backend: `app/api/v1/admin.py`, `app/api/v1/analytics.py`, `app/api/v1/commerce.py`, `app/api/v1/campaigns.py`, `app/api/v1/routes.py`, `app/models/entities.py`, `app/services/rewards_engine.py`.
- Migration: `migrations/versions/0010_integration_snapshots.py`.
- Tests: `tests/test_commerce.py`, `tests/test_phase13_postgres.py`, `tests/test_admin_migration.py`, `tests/test_campaign_migration.py`, `tests/test_notifications_migration.py`.
- Required project records: `docs/PHASE_13_INTEGRATION_AUDIT.md`, this log, `IMPLEMENTATION_STATUS.md`, and `docs/DEVELOPMENT_ROADMAP.md`.

## PostgreSQL blocker and next checks

- Exact blocker at continuation: `psql`, `postgres`, `initdb`, `pg_ctl`, `pg_isready`, Docker and Podman are unavailable; port 5432 is not listening; neither `CROWND_PHASE13_DISPOSABLE_POSTGRES_URL` nor `CROWND_PHASE13_POSTGRES_ACK` is configured. No endpoint was supplied. The existing connected Supabase project was not inspected or used, per the safety instruction.
- Minimal safe provisioning: provide a newly created, short-lived PostgreSQL database (not the connected Supabase project and not production) whose database name contains `test`, `disposable`, or `phase13`, with a dedicated role allowed to create/drop a schema. Run from `backend/` with `CROWND_PHASE13_DISPOSABLE_POSTGRES_URL=<that URL>` and `CROWND_PHASE13_POSTGRES_ACK=I_AM_USING_A_DISPOSABLE_DATABASE`. The opt-in tests create a random `phase13_<uuid>` schema, migrate/test only within it, and drop that schema. Do not use Docker or modify WSL to provision it.
- Until that target is available, PostgreSQL migration DDL/triggers, transaction rollback, checkout/stock/cart/reward/dispute concurrency and multi-worker notification semantics remain unverified. The optional tests are present but skipped; their presence is not verification.
- Re-run the full backend suite, frontend test/lint/build, `compileall`, `git diff --check`, secret-pattern scan and branch sync after any further code changes. No shared-database migration or Phase 13 completion claim is made.
