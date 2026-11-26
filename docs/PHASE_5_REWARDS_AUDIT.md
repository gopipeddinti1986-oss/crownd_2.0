# Phase 5 Rewards, Ledger, and Earnings Audit

**Audit date:** 2026-11-25

**Repository/branch:** `gopipeddinti1986-oss/crownd_2.0`, `arena/e6c9b4f7-crownd-2-0`

**Audited baseline:** Phase 4 commit `4d322f3fcdfd754fb1c82808399a3f6c1f0161ec`; working tree was clean before this audit. No Phase 5 schema or code changes had been made when this audit was written.

## 1. Existing architecture and reusable functionality

### Database and migrations

- SQLAlchemy declarative models live in `backend/app/models/entities.py`; Alembic revisions are `0001_initial_schema.py` through `0005_referral_attribution.py`.
- Monetary values use `Decimal` / `Numeric(12,2)` for orders, rewards, and ledger entries; campaign `reward_rate` is `Numeric(7,3)`, campaign budget is `Numeric(12,2)`, currency is currently INR by default.
- Existing models already represent users/roles, creator and brand profiles, products, campaigns, campaign-product associations, accepted applications, referrals, visitor attribution, order/order items, payment attempts, conversions/events, risk flags, rewards, a basic ledger, payouts and audit logs.
- `Reward` has a unique `order_id`, `creator_id`, amount, status, eligibility date, demo flag, and creation date. The unique order key prevents more than one reward per order, but Phase 4 permits one creator/referral attribution per order; the schema cannot represent multiple creator rewards from distinct attributed order items.
- `LedgerEntry` is currently a small mutable model (`reference`, `user_id`, `entry_type`, `amount`, `currency`, `created_at`) with no source foreign keys, direction, idempotency key, reversal relationship, uniqueness constraint, or append-only guard.
- `Payout` records a creator, amount, `requested` status, and timestamp. There is no administrator approval/settlement/reconciliation workflow and no provider integration. Migration `0004` marks legacy-provenance rewards as demo/non-payable; migration `0005` introduces conversion provenance but does not create fabricated historical rewards.
- The initial migration imports current metadata and uses `create_all`; later migrations have defensive schema inspection. New migration work must remain additive and be tested against that history.

### Campaign reward rules and calculation

- Campaigns already have `reward_model` (`percentage` or `fixed`), `reward_rate`, `budget`, active dates and status. The campaign creation schema validates the basic enum, nonnegative amount and precision. There is no dedicated reward-rule table, per-product override, explicit currency, min order amount, max reward, or cap accounting.
- `backend/app/services/rewards.py::calculate_reward` uses `Decimal`, interprets percentage as a rate over 100, supports fixed rewards and quantizes to two decimals. It does not return a calculation snapshot or validate caps/currency.

### Conversion, order, and payment lifecycle

- Phase 4's `Conversion` is unique by order, with referral/creator/campaign IDs, visitor hash, status, attributed amount, currency, demo flag, reason and timestamps. `ConversionEvent` is unique by conversion/event key. Conversion creation and transition helpers live in `backend/app/services/conversions.py`.
- `OrderItem.referral_id` contains line attribution. Checkout validates attribution and products on the server, constructs line snapshots and computes the eligible attributed amount. Mixed eligible/ineligible items are supported, but the order-level conversion schema still groups the attributed amount by a single referral/creator. Phase 5 must use the item-level referral IDs as the basis for splitting a mixed order into creator-specific rewards without rebuilding attribution or conversion records.
- Successful Demo Payment is a backend simulation. It confirms the conversion and currently creates one demo reward. COD is unpaid at checkout; only the existing administrator collection endpoint after delivery marks collection/payment paid, confirms the conversion and creates a non-demo reward. An ordinary eligible unpaid cancellation transitions conversion history to cancelled and restores stock. Paid-order refund/reversal is not implemented; cancellation of paid orders is rejected.
- `_create_referral_reward` in `backend/app/api/v1/commerce.py` calculates from `Conversion.attributed_amount` using the single campaign default rate, checks a campaign budget, then inserts `Reward` plus a `LedgerEntry`. It is called on demo success and COD collection. This is the key integration hook to replace with a transactional, idempotent reward-generation service.
- Existing commerce tests cover Phase 4 mixed-cart attribution, demo/COD lifecycle, self-referral, cancellation history, and one reward per order, but do not exercise per-item/multi-creator rewards, immutable ledger behavior, approval, reversal, or admin payout simulation.

### Backend APIs and authorization

- FastAPI routes are composed in `backend/app/api/v1/routes.py` and `commerce.py`. Role dependencies use `require_role`; routes use SQLAlchemy sessions and transaction/commit patterns. Rate limiting is provided by the existing auth limiter.
- Existing creator APIs are `GET /rewards/me` and `POST /payouts`; the latter computes available eligible non-demo reward balance and creates a payout request only. Analytics overview performs Python-side reward aggregation and currently excludes demo rewards.
- Existing public schemas are in `backend/app/schemas/commerce.py`; route tests use the `commerce_db` / `commerce_client` fixtures in `backend/tests/test_commerce.py`.
- Admin reward queue, approval, rejection, reversal, simulated payout, reward-rule administration, and brand-scoped financial analytics are absent. All new filters need bounded pagination and ownership constraints; only administrators may mutate reward status or record simulated payouts.

### Frontend

- React/TypeScript/Vite uses `App.tsx` for navigation and a component-based page switch, `services/api.ts` for Axios helpers, React Query for fetching/caching, and existing shared `.panel`, metric, table, and notification styles.
- Creator referral/conversion surfaces are in `frontend/src/components/ReferralAnalytics.tsx`; existing earnings is an `EarningsPage` in `App.tsx` using `/rewards/me` and `/analytics/overview`. It shows an eligible balance and an existing payout-request action; this needs careful replacement/clarification so nothing implies real transfer.
- Brand dashboards use role-scoped data from `/analytics/overview`; admin routes use `/admin/*` guards. Existing frontend tests are Vitest/Testing Library and include service, route, customer commerce and auth coverage.
- No reward details drawer, ledger viewer, admin reward queue or brand reward-performance UI exists at baseline.

## 2. Gaps and integration risks

1. **One reward per order is too restrictive for Phase 4 mixed-cart attribution.** Multiple referral IDs can occur across order lines, so the unique key must move to a reward-per-attributed-line/source combination while preserving existing reward rows and the old API surface.
2. **Current campaign default can be changed after a reward is issued.** Historical rewards need immutable calculation snapshots; generation must copy the exact rule and inputs used.
3. **Campaign budget checking is a read-then-write sum and not concurrency safe.** Any Phase 5 cap must be transactionally reserved/serialized or conservatively validated with database constraints; SQLite does not prove PostgreSQL row-lock behavior.
4. **Current ledger rows are not truly immutable or idempotent.** New financial entries need append-only application behavior, database uniqueness/idempotency keys, reversal references and controlled mutation surfaces. Old ledger rows must remain readable, not silently rewritten into fabricated balanced data.
5. **Reward status `pending` / `eligible` is simple and payout request semantics are partial.** Demo reward status must remain simulated/non-payable. COD must not become `pending` before the existing collection endpoint confirms cash. Approval and payout simulation must be distinctly identified.
6. **Conversion is order-unique but reward basis is item-level.** The reward service must query attributed `OrderItem` rows and group by each item referral/creator/campaign. If multiple eligible items for one creator/campaign/rule exist, define whether they aggregate into one reward per order/creator/rule or remain line-level; use a unique source key to prevent duplicate processing.
7. **Refunds do not exist.** Add a reversible ledger architecture and admin reversal path for cancellation or correction, but do not create a fake customer refund process or claim actual refund integration.
8. **Role/privacy boundaries need explicit tests.** Creator can see their financial data only; brands can see aggregate and creator campaign performance for their campaigns but no customer PII; only admin can approve/reject/reverse or create simulated payout records.
9. **Historical records are incomplete.** Existing Phase 3/4 rewards may have order-level basis only, and existing ledger rows are not guaranteed to have source keys. Keep these historical rows in place and distinguish legacy snapshots; do not generate new rewards retroactively or pretend old records have verified item attribution.
10. **Current analytics use Python aggregation and existing payout requests reserve balances weakly.** New reporting should use scoped database aggregation and distinguish demo, COD awaiting collection, review/pending, approved liability, reversals and simulated payout history. Simulated payouts must not be represented as actual paid money.

## 3. Recommended Phase 5 architecture

- Keep existing `Campaign`, `CampaignProduct`, `Referral`, `Order`, `OrderItem`, `Conversion`, `Reward`, `LedgerEntry`, `Payout`, `AuditLog`, and role/auth architecture. Add an additive reward-rule model for campaign default and product-specific override, plus reward calculation snapshots/events and explicit simulated payout records where current entities cannot express them safely.
- Use deterministic precedence: active product-specific rule for the attributed item, otherwise campaign default. If no active dedicated rule exists, use the existing campaign default as an explicitly snapshotted legacy campaign rule. Reject invalid amounts/rates/currency/date windows and duplicate overlapping active rules at the same scope.
- Generate rewards transactionally from eligible order items after Demo Payment success or after COD collection confirmation. Group by order + creator + campaign + selected rule (or use line-level reward records with a unique source-item key); preserve item values and conversion provenance. Self-referral, inactive/unapproved participation, invalid campaign/product/attribution, cancellation, zero eligible amount and ineligible conversion cannot produce payable reward.
- Use Decimal arithmetic and the current two-decimal INR quantization, with documented `ROUND_HALF_UP`; snapshot original/eligible/excluded amounts, rule type/rate/fixed amount/caps, currency, item/product IDs, formula, rounding and generated amount. Never recompute existing rewards from edited rules.
- Treat Demo as a separate simulated reward state and keep it out of actual payable/liability totals. Treat COD as `PENDING_COLLECTION` until the existing admin collection API succeeds, then create the normal pending reward. Use scheduled/administrative eligibility transition based on the stored 30-day eligible date; no worker infrastructure exists, so expose a safe admin or query-derived maturity workflow and document it honestly.
- Make ledger entries append-only at the service/API level with unique idempotency keys and source references. Represent reward creation as positive liability and reversal as a negative entry referencing the original. Record payout simulation as an explicit simulation-only event/record, not a real transfer. Existing legacy ledger rows remain untouched.
- Add scoped creator APIs (summary, paginated rewards/detail/ledger), brand campaign analytics, and admin overview/search/review/action/ledger/audit APIs. Apply RBAC and exact ownership predicates in SQL. UI screens should consume only API-backed values and disclose the absence of real payouts.
- Validate migration against a fresh SQLite database and an upgraded current Phase 4 schema with existing order/reward/ledger rows; downgrade/re-upgrade must preserve what the prior revision owns. Do not generate retroactive financial records.

## 4. Verification targets and limitations

Test percentage/fixed/product override/rounding/caps, mixed creators and excluded lines, Demo/COD gates, reward idempotency, risk status, approval/rejection/reversal, ledger references/uniqueness, simulated payout, role/ownership denials, filtered aggregates/pagination, legacy reward compatibility and migration upgrade/downgrade/re-upgrade. Run backend suite/compile, frontend suite/typecheck/lint/build, diff and secret checks. PostgreSQL concurrent cap reservation, production-scale load, browser E2E, external payment/refund/payout provider integrations and legal/accounting review are separate limits unless the repository environment can genuinely verify them.

## 5. Phase 5 implementation and verification addendum (2026-11-25)

The above sections preserve the **baseline findings**; the repository now contains the Phase 5 implementation described in `docs/PHASE_5_REWARDS.md`. Key decisions and verification outcomes:

- Added revision `0006_rewards_ledger`, product-scope and campaign-scope rules, reward-event and simulated-payout tables, item-level cart attribution, reward provenance/snapshot columns, ledger idempotency/reversal references, and SQLite/PostgreSQL triggers preventing SQL-level update/delete of ledger and reward-event history. The migration is additive and checks for unsafe Phase 5 rollback data.
- Existing Phase 1–4 conversion/order/payment/referral tables remain the source of truth. No retroactive reward or liability is synthesized; old reward rows are tagged with an unverified legacy snapshot.
- Rule precedence is product-specific, campaign default, then existing campaign rule. Calculation uses Decimal/INR/ROUND_HALF_UP and snapshots the exact basis. Reward source keys and ledger keys are deterministic.
- COD creates no reward or liability at checkout; after delivery, only the existing admin collection action confirms cash and creates a pending reward plus ledger credit. This is intentionally stricter than an estimate-only pending-collection row. Demo rewards are visibly simulated and never payable.
- Creator and brand financial APIs, admin rule/reward/ledger/history APIs, secured admin lifecycle actions, React creator earnings, brand reward analytics and the admin reward operations page are registered and implemented. Legacy creator `POST /payouts` now returns 410 instead of creating a request that could imply payout processing.
- Verification performed: backend **43 passed**, Python compile succeeded; fresh SQLite upgrade/downgrade/re-upgrade succeeded; an isolated copy of the existing Phase 4 SQLite schema upgraded to head successfully. Frontend **26 passed**, TypeScript/Vite production build and ESLint succeeded (existing bundle-size advisory).
- The in-use local `backend/crownd.db` was accidentally selected by an initial migration test and the migration failed before revision advance. Only empty artifacts from that attempted migration were removed; the DB was then checked for SQLite integrity (`ok`) and remained at revision `0005_referral_attribution`. A separate copy was used for the successful existing-schema upgrade test. No local production/preview data was changed by the cleanup; table counts were zero for the temporary artifacts.
- Not verified: PostgreSQL runtime/lock behavior under concurrent requests, real production dataset upgrade, browser end-to-end, external money movement (explicitly out of scope), real refunds, and financial/legal review. The campaign budget/cap lock path is designed for PostgreSQL but still needs a concurrency test there.
