# Phase 5 — Rewards, Ledger, Earnings & Financial Analytics

**Status:** Implemented on `arena/e6c9b4f7-crownd-2-0` (verification below).

**Scope boundary:** There is no payment gateway, payout provider, money movement, or actual transfer. Every simulated payout record explicitly says that no actual money was transferred.

## Business behavior

### Rule selection and deterministic calculation

- Admins configure one rule per campaign/product scope. Rules support percentage or fixed INR amounts, validity windows, minimum eligible sales, per-reward caps, creator caps, and campaign caps.
- Rule precedence is deterministic: **active product-specific rule → active campaign-wide rule → existing campaign default**, with the selected source and rule values copied into each reward snapshot.
- The backend calculates from validated `OrderItem` rows and persisted Phase 4 attribution. It uses Python `Decimal`, INR `Numeric` values, two-place `ROUND_HALF_UP`, and records formula, inputs, item IDs, eligible/excluded totals, caps and computed amount in `Reward.calculation_snapshot`.
- Rewards are grouped by order, attributed creator, campaign and selected rule; the snapshot retains every included item. The unique deterministic `source_key` plus ledger idempotency keys prevent repeat generation.
- Only eligible, attributed product items are used. The engine rechecks referral/campaign/product eligibility and accepted participation, rejects self-referrals, excludes ineligible items, and consults open risk flags. No reward can be generated without a confirmed conversion (except the explicitly simulated demo path).
- Per-reward maximums apply to demo and non-demo calculations. Creator/campaign cumulative caps and campaign budget constrain non-demo liabilities only; demo records are simulation-only and do not consume or reserve those totals. The service obtains a campaign row lock for payable cap/budget checks on PostgreSQL; SQLite does not prove production lock/concurrency behavior.

### Demo and COD distinction

- Demo success creates a `simulated` reward, marks it `is_demo`, and appends a memo ledger entry. These rows are disclosed as simulated, not payable, excluded from actual liability, ineligible for approval/reversal/payout simulation, and never cause a transfer.
- COD checkout does **not** create a reward or ledger liability. A reward is generated only after the order is delivered and an administrator calls the existing collection-confirmation endpoint. That transaction marks COD paid/confirmed, records audit/conversion history, creates the reward in `pending` (or `under_review` when risk exists), and appends the credit. A failed/duplicate collection cannot create another reward or ledger entry.
- Cancelling an unpaid COD order cancels the conversion and does not create a financial record. Paid-order cancellation/refunds remain unsupported by the existing order workflow; CROWND does not claim to issue refunds.
- A 30-day `eligible_at` hold is stored and enforced by the admin approval action. No background scheduler is present; administrators must approve after the hold has elapsed.

### Ledger, reversals, and administrative controls

- Migration `0006_rewards_ledger` adds rule, event and simulated-payout tables, reward calculation/provenance fields, cart-line referral attribution, ledger idempotency/provenance fields and indexes. Existing reward/ledger rows are retained; legacy reward snapshots are marked unverified rather than reconstructed or repriced.
- New financial ledger entries are append-only. ORM listeners reject update/delete for ledger and reward-event records; migration triggers also reject direct SQL UPDATE/DELETE on SQLite and PostgreSQL. Reversals append a debit referencing the original credit. No reward or ledger row is deleted to represent a cancellation/correction.
- Admin-only review actions approve, reject, reverse and record simulated payouts. Approval requires a cleared risk check, a confirmed conversion, paid order, non-demo reward and elapsed hold. Simulated payout records add a memo entry and disclosure but do not change the actual liability balance.
- The legacy creator `POST /payouts` request is retired with HTTP 410. There is no user-facing actual payout request or transfer workflow.

## API surfaces

All routes are under `/api/v1`; all financial endpoints require the stated role and are backed by scoped SQL predicates.

| Role | Endpoint | Purpose |
|---|---|---|
| Creator | `GET /creator/earnings/summary` | Reward totals, states, demo totals and net ledger liability |
| Creator | `GET /creator/rewards` | Filterable, paginated creator-owned reward records |
| Creator | `GET /creator/rewards/{id}` | Own reward snapshot and lifecycle/ledger history |
| Creator | `GET /creator/ledger` | Paginated own immutable ledger entries |
| Brand | `GET /brand/reward-analytics` | Campaign/creator financial aggregates, with customer details excluded |
| Admin | `GET /admin/rewards/summary`, `/admin/rewards` | Financial summary and filtered/paginated management queue |
| Admin | `GET /admin/rewards/{id}` or `.../{id}/history` | Reward snapshot, events, audit history, risk context and ledger |
| Admin | `GET /admin/ledger` | Paginated ledger audit view |
| Admin | `GET/POST /admin/reward-rules`, `PUT /admin/reward-rules/{id}`, `PATCH /admin/reward-rules/{id}/active` | Configure and manage rule scopes |
| Admin | `POST /admin/rewards/{id}/approve`, `/reject`, `/reverse`, `/simulated-payout` | Controlled lifecycle actions; rejection/reversal require a reason |

Creator and brand responses omit customer names, contact data, addresses and customer IDs. Admin views retain necessary creator/customer-order context only where already authorized by the existing admin role; reward analytics do not return customer PII. Detailed free-text risk notes are admin-only; creator reward history exposes risk codes/status without those notes.

## Frontend

- Creator Earnings uses the new summary, paginated reward and ledger APIs; demo rewards are explicitly not payable, and the actual payout button is removed.
- Brand campaign referral analytics includes reward liability, pending/approved and simulated amounts plus creator aggregates, and explains that customer data is excluded and no transfer occurs.
- Admin Reward Operations provides filtered/paginated reward review, rule create/edit/activation, approval/rejection/reversal/simulated-payout controls, reward snapshots/lifecycle history, and an append-only ledger view.
- Route access is role-gated; server authorization remains authoritative. UI totals come from the backend and no hard-coded success or payout values are introduced in Phase 5 surfaces.

## Migration and compatibility

1. Back up the deployment database before migration.
2. Apply `alembic upgrade head`; revision is additive at `0006_rewards_ledger`.
3. Review legacy records before relying on reward summaries: legacy amounts are preserved but their historical item basis/rule is explicitly marked unverified. The migration does not create retroactive rewards or payout entries.
4. Downgrade is guarded: it refuses to restore the prior one-reward-per-order constraint if multiple rewards exist and refuses to drop Phase 5 rules/events/payouts, generated rewards or idempotent ledger entries. Pre-existing reward and ledger rows are retained, but Phase 5 fields/structures are removed on an empty-data downgrade. Do not downgrade production after Phase 5 records have been created; the migration is deliberately blocked in that case.

## Verification performed

- Backend tests: **43 passed**, with the existing Starlette/httpx deprecation warning.
- Backend `compileall`: succeeded.
- Fresh SQLite migration: `upgrade head → downgrade 0005_referral_attribution → upgrade head` succeeded.
- Existing Phase 4 schema clone: `upgrade head` succeeded. The source local database remained at revision `0005_referral_attribution`; it was not intentionally upgraded.
- Frontend Vitest: **26 passed**; TypeScript/Vite production build and ESLint passed. Vite reported its existing >500 kB chunk advisory.
- PostgreSQL concurrency/load, browser E2E, external gateway/payout/refund integrations and accounting/legal review are not verified or included.
