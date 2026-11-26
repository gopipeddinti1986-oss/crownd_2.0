# Phase 4 referral attribution audit

**Audit baseline:** prior to Phase 4 implementation on 2026-11-25. This audit records the original implementation state and risks; the baseline statements below are historical, not a description of the post-implementation branch.

## Existing system inventory

| Area | Before implementation | Reuse/extension decision |
|---|---|---|
| Referral links | Existing `Referral` ties a creator and campaign to a code. | Extend it with optional product destination and preserve existing accepted `Application` as participation. |
| Clicks | Existing `Click` rows and click counter; session hash was not populated. | Persist hashed opaque visitor IDs, sanitized host and coarse device category. Keep the counter compatible, count valid clicks and derive analytics from events. |
| Cookies | Existing HMAC-signed `crownd_referral` cookie. | Preserve compatibility; add signed HttpOnly `crownd_attribution` visitor token and durable first/last touch state. |
| Commerce | Existing authenticated multi-line cart and checkout; order referral summary existed, line-level attribution did not. | Add line-level referral FK, preserve order idempotency, derive eligible products and amounts on the server. |
| Payments/rewards | Phase 3 provides simulated Demo Payment and unpaid COD, with COD collection controlled by admin. | Reuse those lifecycle transitions; only successful simulated demo or collected COD confirms a conversion; calculate reward from attributed lines. |
| Analytics/UI | Existing basic link/click and aggregate dashboards. | Add role-scoped creator, brand and admin referral analytics/review surfaces without customer contact/address data. |

## Baseline risks found

1. Campaign date windows were not enforced in referral eligibility.
2. Product eligibility was coarse; mixed carts could not assign attribution to only eligible lines.
3. The signed referral cookie did not persist durable first/last touch or customer association.
4. Click rows were not useful for visitor analytics; empty session hashes could be counted incorrectly.
5. There was no order-backed conversion state machine, self-referral prevention, or explicit COD/demo conversion state.
6. Creator link lifecycle and admin review/analytics were incomplete.

## Design and acceptance decisions

- Reuse `Referral`, `Application`, existing cart/order/item/payment/reward entities; do not create a competing link identity or accept frontend attribution authority.
- Use **last valid referral** within the configured attribution window (seven days by default). Preserve first touch, let a new valid link replace last touch, and never let direct/invalid browsing clear it.
- Revalidate active creator, brand, campaign status and dates, accepted participation, active referral, product ownership/status, and campaign-product eligibility server-side during click and checkout. Product scope applies to individual order lines, allowing mixed carts.
- Create at most one conversion per order. Clicks, views, cart additions, and unpaid COD orders are not confirmed conversions. Demo results are explicitly simulated; COD remains pending until authorized post-delivery cash collection. Keep cancellation history as conversion events and prevent duplicate rewards.
- Self-referrals are ineligible; store explainable review flags without invasive fingerprinting or automatic account bans. Do not store raw IP/full user-agent or expose customer contacts/addresses in creator/brand analytics.
- Migration is additive; preserve existing rows and label historical referral orders `historical_not_revalidated` rather than asserting a retroactive paid conversion.

## Implementation and verification (2026-11-25)

Implemented in the current branch with migration `0005_referral_attribution`: durable visitor attribution, product-level order attribution, conversion/event history, risk flags, eligibility/link services, role-scoped paginated APIs/filters, and creator/brand/admin dashboards. The detailed behavior and limits are in [`referral-attribution.md`](referral-attribution.md).

- Backend: **38 passed**, one existing Starlette/httpx deprecation warning; Python compileall passed.
- Frontend: **24 passed**, TypeScript, ESLint and production build passed. Vite reports a pre-existing-style advisory that the ~772 kB main JS chunk exceeds 500 kB.
- SQLite migration: fresh upgrade to head, downgrade to `0004_payment_options`, re-upgrade to head passed; head is `0005_referral_attribution`.
- Secret-pattern scan and `git diff --check` passed after review.
- Not verified: PostgreSQL migration/runtime or multi-worker race/load behavior, browser E2E, external payment/refund provider, and consent/retention/legal/privacy review. The app still has no paid-order refund/reversal workflow; paid orders cannot use ordinary cancellation. `/r/{code}` continues to return destination metadata rather than a full redirect.
