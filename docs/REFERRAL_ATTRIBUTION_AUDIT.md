# Referral attribution audit — Phase 4 baseline

**Audited branch:** `arena/e6c9b4f7-crownd-2-0`  
**Baseline commit:** `e02ad16dd9ff042b3808649fe8e349dfd1984a4d`  
**Audit date:** 2026-11-25

This is a source audit, not an independent security review. It records the behavior before Phase 4 implementation.

## Existing architecture (reuse points)

| Area | Existing implementation | Phase 4 implication |
|---|---|---|
| Participation | `Campaign` and unique `(campaign_id, creator_id)` `Application`; accepting an application creates a `Referral`. No separate Collaboration model exists. | Use accepted `Application` as the current participation authorization; do not invent another collaboration layer. |
| Referral links | `Referral` maps creator + campaign to unique code, `active`, click counter, and timestamp. `/referrals/me` lists a creator's referrals. | Extend this as the link record; add optional product destination rather than a second link table. Make generation idempotent and ownership checked. |
| Clicks | `Click` contains referral ID, timestamp, and a `session_hash` column. `/r/{code}` increments `Referral.clicks` and inserts a Click, but never populates the hash. | Replace the counter as analytics source with persisted events; retain the counter only for compatibility or derive/update it atomically. Store only opaque visitor hashes, not raw IP. |
| Referral visit endpoint | Authenticated API router exposes `GET /api/v1/r/{code}`; it returns JSON destination metadata, not an HTTP redirect. Frontend `/r/:code` calls it then navigates. | Keep the frontend handoff, validate first, return a relative internal destination, and ensure invalid links do not alter attribution. A server redirect is not required by the current SPA architecture. |
| Cookie attribution | Commerce service signs `referral_id.expiry` using HMAC with `JWT_SECRET`, sets HttpOnly/SameSite cookie scoped to `/api/v1`; configured window is 7 days. Each valid click replaces the cookie, approximating last-click. | Preserve signed-cookie behavior, add first/last-touch state and visitor continuity in a DB row keyed by a hash of a random signed visitor token. Login can associate customer ID without accepting client creator/campaign IDs. |
| Checkout / orders | Checkout reads cookie server-side; validates published campaign/active verified creator and stores one `Order.referral_id`. Product restriction rejects the entire mixed cart if a campaign is product-specific. | Keep `Order.referral_id` as compatibility summary, add item-level attribution so only eligible lines are credited; preserve order/checkout idempotency. |
| Payment / rewards | Demo success creates simulated reward; COD collection after delivery creates pending reward; cancellation only supports unpaid orders. | Conversion state must be distinct from reward and order; demo conversions remain explicitly simulated/non-payable; COD stays pending until collection; cancellation must preserve a terminal conversion record. |
| Analytics / UI | Creator referrals page shows code/click counter only. Dashboards use broad aggregate endpoints. No referral-link management, conversion table, risk review, or customer-safe conversion detail view exists. | Add role-scoped attribution analytics/API and focused creator/brand/admin views; keep customer details private. |
| Migrations/tests/docs | `0001`–`0004` migrations, commerce tests cover signed referral click and checkout attribution, but not expiry/last-touch/multi-product conversion lifecycle. Existing `docs/referral-attribution.md` explicitly notes these gaps. | Add one additive migration and lifecycle/security/integration tests; update historical documentation without claiming unsupported completeness. |

## Findings and risks

1. **Participation is not checked at click or checkout.** A Referral row is the only evidence of creator participation, but it can outlive application changes. Current click/checkout checks do not verify an `accepted` application or date-window eligibility.
2. **Campaign lifecycle is incomplete for attribution.** `starts_at`/`ends_at` exist, but referral validation only checks `status == published`; start/end dates are ignored.
3. **Product eligibility is too coarse.** `Campaign.product_id` can represent one product or null (broad campaign). `_validate_referral_for_products` rejects a whole mixed cart when only some items match, and reward creation uses full order amount.
4. **No durable attribution history.** The signed cookie identifies only a referral and expiry. No first touch, visitor record, customer association, or click-to-order chain is persisted. Refreshing a valid referral resets its seven-day cookie expiry.
5. **Clicks are not unique visitors or conversions.** The endpoint increments a Python counter (susceptible to lost updates), writes a click with an empty session hash, and returns JSON rather than an actual server redirect. Current dashboard counts referrals/clicks, not conversions.
6. **No conversion lifecycle or duplicate guard exists.** Order FK is not a conversion record; demo/COD payment status transitions do not update conversion state. There is no conversion uniqueness constraint or cancellation history.
7. **Creator links are automatic, not creator-managed.** Accepting an application auto-creates a code; creators cannot select eligible destinations, list/filter details, deactivate or regenerate links. Current API has only `/referrals/me`.
8. **No foundational fraud flags.** Self-referral is not checked; click bursts, repeat-customer patterns and suspicious orders are not recorded. Raw IP is not currently stored, which is privacy-preserving and should remain so.
9. **Historical semantics are ambiguous.** Existing order-level attribution does not prove that every line was campaign-eligible. Historical rows should be retained but not silently reclassified as verified conversions.
10. **No Collaboration model exists.** Implement eligibility using accepted `Application` (the existing approval record), rather than inventing a parallel participation system. If the product later adds collaborations, it should map explicitly to the same eligibility policy.
11. **Frontend referral page is a basic link/click table.** No creation/deactivation actions or real conversion metrics exist; analytics cards elsewhere may describe orders/revenue broadly and should not be relabeled as referral conversions without a conversion query.

## Security and privacy observations

- Creator/campaign are resolved from a database Referral at the API; checkout does not accept creator IDs, campaign IDs, or conversion status. Preserve this invariant.
- The HMAC cookie protects the referral ID from client edits, but does not itself persist first/last touch, authenticate a visitor, or enforce eligibility consistently.
- Referral code lookup is indexed/unique. `/r/{code}` currently lacks explicit rate limiting and click metadata validation.
- Do not persist raw IP, full user-agent, email, or phone in click records. Use a random signed visitor cookie and a one-way hash for analytics; collect only coarse device/referrer-origin metadata if needed.
- Campaigns, creators, links and products can change state after a click. Eligibility must be checked again at order creation and conversion confirmation using a single service.
- Customer order responses must not expose customer PII to creators/brands. Conversion analytics should return aggregated/anonymized customer counts, not customer records.
- Duplicate rewards are partly guarded by unique `Reward.order_id`, but this is not a conversion guard and does not handle item-level reward basis. The new conversion record must be independently unique and transactionally aligned with payment transitions.

## Incremental implementation plan

1. **Data and policy foundation:** add product eligibility association for campaigns (while retaining legacy `Campaign.product_id`), product-level order attribution, visitor attribution state, conversion/event records, and explainable risk flags. Add keys/indexes and an additive `0005_referral_attribution` migration. Preserve legacy referral and order rows.
2. **Eligibility/link services:** centralize active/verified creator, accepted application, campaign status/date, active link, and eligible-product checks. Keep `Referral` as link; add creator-owned link generation/list/deactivation with unique-code collision retries and idempotent reuse.
3. **Click and signed persistence:** validate before modifying attribution; rate-limit; issue/retrieve a signed opaque visitor token; persist first/last valid referral and click events with hashed visitor IDs; store sanitized origin and coarse device class only. Keep current relative SPA destination response.
4. **Checkout and conversion state machine:** attribute only eligible order items. Create one conversion per attributed order in the same order transaction; demo success confirms a flagged simulated conversion, COD remains pending until admin collection, and cancellation transitions conversion to cancelled/reversed without deleting history. Self-referral is ineligible and flagged. Add transaction-level duplicate protection.
5. **Analytics and operations:** role-scoped paginated link/conversion/risk queries and explicit formulas for clicks, unique visitors, orders and conversions. Add creator link/conversion dashboard and brand campaign performance, plus admin search/flag/link deactivation with audit logs. Never expose customer contacts/addresses.
6. **Verification/docs:** unit, security, multi-item, migration, integration, creator/brand/admin API, front-end, typecheck/lint/build; document any out-of-scope product-view/cart-add event telemetry and production PostgreSQL/concurrency follow-up.

## Baseline limitations

This audit does not establish actual redirect delivery, unique visitor measurement, campaign end-date enforcement, creator application revalidation, item-level attribution, conversions, self-referral defense, or referral dashboards. Those must not be claimed until implemented and verified. The existing 7-day value is the configured cookie duration; because expiry is refreshed on each click, the effective current behavior is not a fixed seven-day window from first touch.
