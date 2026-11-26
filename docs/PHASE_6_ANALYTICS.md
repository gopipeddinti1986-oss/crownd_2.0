# Phase 6 — Campaign management and analytics

Updated: 2026-11-25. This is the implementation record for campaign lifecycle and analytics in the CROWND repository. It builds on the existing campaign, application, referral, order-item, conversion, payment and reward records; it does not add a second attribution or payment system.

## Delivered

- Brand-scoped campaign listing, detail and updates, with query filters, sorting and pagination; draft/published/paused/completed/cancelled lifecycle actions; structured objectives, audience, creator requirements, visibility, performance goals and eligible product selection.
- Campaign management and analytics workspaces for brands, a campaign detail report, and aggregate admin analytics. The dashboards use API response data and expose date-window filters, campaign/product filters where available, creator and product comparisons, time-series/funnel data, deterministic rule-based observations, loading/error/empty states, and CSV actions.
- Server-side reporting windows: UTC today, yesterday, rolling 7/30/90-day periods, campaign lifetime and custom date ranges capped at ten years. Campaign-specific reporting is bounded to campaign dates. Product filter IDs are validated against campaign scope.
- Database-derived rollups for clicks, distinct anonymous visitor tokens, tracked product views/cart additions, order/conversion/payment states, attributed order-item values and generated rewards by state. Product and campaign revenue are attributed by each order item's stored referral, so mixed-cart items are not assigned wholesale to one creator/campaign.
- Additive migration `0007_campaign_intelligence`, dependent on `0006_rewards_ledger`; its upgrade supports both the current metadata-driven fresh baseline and existing databases where campaign configuration columns are absent. Downgrade intentionally leaves additive data/columns in place to avoid deleting configuration on fresh databases.
- Brand ownership checks, role gates, hidden/unlisted campaign discovery restrictions, customer-PII-free analytics payloads and CSVs, rate limits on reporting/export endpoints, and spreadsheet-formula escaping in CSV output.

## Definitions and financial safeguards

- **Confirmed revenue**: sum of attributed order-item line totals for non-demo conversions whose order is paid. COD orders are not confirmed revenue until cash collection/payment state is recorded as paid. An unpaid COD conversion is pending, not confirmed revenue.
- **Pending revenue**: attributed order-item value for pending conversions on orders in pending/unpaid payment state. Cancelled, reversed/refunded and demo values are separately reported and excluded from confirmed revenue.
- **Demo**: simulated order/reward counts and values remain separately labeled. They do not count as genuine revenue, actual spend or payable rewards.
- **Reward states**: generated reward value is reported separately for pending, pending collection, under review, eligible, approved, reversed and rejected states (plus simulated reward value). Pending COD rewards awaiting collection are broken out instead of being conflated with confirmed revenue.
- **ROI and cost per conversion**: unavailable. Campaign budget is a ceiling, not actual spend. Reward efficiency (confirmed revenue divided by generated non-demo reward value, excluding reversed/rejected rewards) is a separate ratio and is not ROI or cash spend; reward values may still be pending and are not actual payouts.
- Clicks and anonymous visitors are not conversions. Customer names, emails, shipping addresses, payment references and visitor hashes are not included in brand/admin analytics or their exports. The conversion export uses an opaque order reference, not customer information.

## Endpoints and implementation

- Brand campaign management: `/api/v1/brand/campaigns`, `/api/v1/brand/campaigns/{campaign_id}`, `/api/v1/campaigns/{campaign_id}` (update) and the existing status transition endpoint.
- Brand reporting: `/api/v1/brand/analytics/overview`, `/campaigns/{campaign_id}`, `/creators`, `/products`, and `/export` under the API v1 prefix.
- Admin aggregate reporting: `/api/v1/admin/analytics/overview`; admin access is required.
- Main aggregation logic is in `backend/app/services/analytics.py`; endpoints are in `backend/app/api/v1/analytics.py` and `campaigns.py`; UI is `frontend/src/components/CampaignIntelligence.tsx`.

## Verification performed

- Full backend suite on the final implementation tree: `JWT_SECRET=test-secret-that-is-long-enough-for-testing ./.venv/bin/pytest -q` — **53 passed**, one upstream Starlette/httpx deprecation warning.
- Frontend on the final implementation tree: `npm test -- --run` — **32 tests passed**; `npm run lint` and `npm run build` passed. Vite reports a ~835 kB minified JS chunk; code splitting remains advisable. Recharts emits zero-size container warnings under jsdom tests; production chart sizing is responsive.
- Migration tests verify SQLite fresh upgrade → downgrade to `0006` → re-upgrade and a simulated historical `0006` schema with Phase 6 columns removed → `0007` upgrade. A copy of the existing local SQLite DB was also upgraded to `0007_campaign_intelligence`. The downgrade is intentionally non-destructive and keeps the new columns; this is documented in migration code.
- `python -m compileall -q app migrations/versions tests` and `git diff --check` passed on the final code tree. Security tests cover brand isolation, role authorization, privacy omissions, unlisted campaign discovery and CSV formula escaping.

## Limitations and follow-ups

- PostgreSQL migration behavior, query plans, concurrency/load behavior, production browser E2E and external payment/refund/COD operations were not verified in this environment. The migration's PostgreSQL JSON defaults/check constraint need review against the deployed PostgreSQL version before production deployment.
- No payment provider, actual campaign-spend ledger, real payout settlement or legal/tax determination was added. No financial or legal advice is implied.
- Analytics date filters use order-created time for commerce rows and event-created time for clicks/activity/rewards. A conversion confirmed after its order was created remains in the order-created reporting window; users should interpret these as cohort/order-date reporting.
- Admin analytics is aggregate/filter-focused, not a full customer/order investigation tool. No customer data is intentionally exposed.
- Existing Phase 1–5 behavior is preserved; this milestone does not claim all earlier roadmap gaps are closed.
