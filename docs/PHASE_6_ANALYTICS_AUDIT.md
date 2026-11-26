# Phase 6 Campaign Management & Analytics Audit

**Audit date:** 2026-11-25

**Branch:** `arena/e6c9b4f7-crownd-2-0`

**Baseline:** Phase 5 commit `57190304edff24341a54a04ce7c9778770f16477`; working tree was clean at audit start. This file captures the pre-Phase 6 state; it is not a claim about the implementation added afterward.

## 1. Existing campaign architecture

Campaigns are represented by the existing `Campaign` model in `backend/app/models/entities.py`, owned by `brand_id` and linked to optional primary product, active date window, title/slug/description/category/platforms, reward model/rate/budget, status and creation time. Eligible products are represented by `CampaignProduct`; the single `product_id` remains a compatibility field. Creator participation reuses `Application`, and referral codes reuse `Referral`. Eligibility checks in `backend/app/services/referrals.py` require a published and in-date campaign, active verified participants/brand and eligible active products. Existing campaign status values include `draft`, `published`, `paused`, `completed`, `cancelled`, and `rejected`; public/creator application and referral behavior treats `published` as active.

`POST /campaigns` creates a draft and checks product ownership. `GET /campaigns` is a public discovery list with rudimentary query/status/offset/limit filtering. `GET /campaigns/{id}` is public. `PATCH /campaigns/{id}/status` has a small legacy transition map and uses a generic dictionary. `PUT /campaigns/{id}/products` has ownership checks and disallows brand edits while published. There is no campaign edit/details management contract, paginated brand-owned management list, explicit status transition service, search/sort contract, or campaign lifecycle UI. Existing operations must be extended in place, not duplicated.

## 2. Existing analytics architecture

Analytics is distributed across:

- `GET /analytics/overview` and `/analytics/timeseries` in `backend/app/api/v1/routes.py` (role-dependent legacy summaries).
- `GET /creator/referral-analytics`, `/creator/conversions`, `/brand/campaign-analytics/{campaign_id}`, and admin referral/conversion/risk endpoints in the same router.
- `GET /brand/reward-analytics` and creator/admin reward/ledger APIs in `backend/app/api/v1/rewards.py`.
- `backend/app/services/referrals.py` for privacy-conscious click, distinct opaque visitor token, product-view/cart-add attribution and eligibility recording.

Phase 4 campaign analytics checks campaign ownership for brand users and uses `Click`, `ReferralActivity`, `Conversion`, `Order`, `OrderItem`, and `Referral`. It returns counts and a limited creator/product breakdown. Some aggregation happens in Python; some is SQL. It has relative `days` windows, not reusable inclusive date range presets/custom bounds; existing rates use confirmed conversions divided by unique visitors. Legacy `/analytics/overview` mixes broad order totals, derives campaign clicks from a mutable counter and has inaccurate/non-item-level scope, so it is not suitable as the source for new Phase 6 financial intelligence.

## 3. Available database entities and trusted data

- **Campaigns/brands/products:** `Campaign`, `CampaignProduct`, `BrandProfile`, `Product`, `User`; product category/status/price and campaign dates, status, budget and reward defaults are available.
- **Participation/creator:** `Application` and `CreatorProfile`/`User`; accepted participation and creator identity can be scoped to campaign.
- **Traffic:** `Click` holds valid event timestamp, hashed opaque visitor ID, referral ID, sanitized referrer host and coarse device; `Referral.clicks` is a compatibility counter and should not be summed with `Click` rows. `ReferralActivity` tracks product-view/cart-add only when attribution exists and product is eligible.
- **Attribution:** `Referral`, `VisitorAttribution`, `OrderItem.referral_id` and `Conversion` provide campaign/creator and line-level attribution. `Conversion` is order-unique, includes lifecycle status, attributed amount, currency, simulated marker and timestamps.
- **Commerce/payments:** `Order` and immutable purchased `OrderItem` snapshots include order amount/payment method/payment status/order status and created timestamp. COD is not paid until admin collection. Demo is simulated and must not count as real confirmed revenue. Cancelled orders and conversion lifecycle are represented separately.
- **Rewards/ledger:** `Reward` includes campaign/creator/product/order/conversion, demo flag, amount, lifecycle, snapshot and timestamps. `LedgerEntry` records immutable credit/debit/memo with reward/order/campaign links. Demo records and simulated payout records are explicitly identifiable.
- No campaign invoice/spend/marketing-cost model exists. `Campaign.budget` is a ceiling, not proof of money spent. No product impression events, actual product page view outside attributed activity, exposure/impression counts, tax/refund/partial refund amounts, or real payout settlements are represented.

## 4. Existing metrics, missing metrics, and definitions risk

Available from actual records: valid referral clicks, distinct non-empty opaque visitor hashes, attributable product views/cart additions, order-backed conversions by lifecycle/payment method, order-item attributed values, eligible item quantity, confirmed paid COD or simulated demo distinction, campaign/product/creator reward records, and campaign/creator participation counts.

Not available and must not be fabricated: marketing spend, actual campaign expense/budget utilization, product impressions for non-attributed visitors, customer purchase funnel outside attributed touch, actual transferred payouts, actual refund amounts, tax/shipping breakdown, and a reliable external-channel exposure denominator. The new ROI endpoint/UI must return `available: false` when no independently recorded campaign costs exist; a budget cannot stand in for spend. Revenue must be computed from order-item snapshots matching campaign attribution and payment state, never the whole mixed-cart order total. Avoid counting order-unique conversions once per product and then summing those counts as if product counts were additive.

## 5. Existing endpoint and authorization inventory

- Public discovery: `GET /campaigns`, `GET /campaigns/{id}`.
- Brand writes: `POST /campaigns`; product associations at `PUT /campaigns/{id}/products`; status at `PATCH /campaigns/{id}/status`; existing brand applications/review and matching routes.
- Analytics: the overview/timeseries legacy routes; creator referral metrics/conversion list; brand campaign performance; brand rewards aggregates; admin reward and referral review endpoints.
- Auth uses `current_user`/`require_role`; existing brand campaign endpoints variously return 403 or conceal missing/foreign ownership. The new management and campaign analytics surfaces need exact `Campaign.brand_id == user.id` SQL scoping, admin-only platform aggregates, bounded pagination and safe response models. No new financial values should be supplied by clients.

## 6. Existing frontend architecture and tests

`frontend/src/App.tsx` contains role navigation and page selection. React Router links provide URL paths; server state uses TanStack Query and `frontend/src/services/api.ts` wraps Axios. `recharts` is already installed and used by dashboard UI, so no chart dependency is needed. `ReferralAnalytics.tsx` is the existing brand referral analytics page and includes campaign/product/time-window selectors, KPI tiles, creator/product conversion lists and reward aggregates; it is not a complete campaign workspace, has limited fields/filters, and does not provide trends/ROI or complete per-creator/product comparisons. Campaign list/detail UI is largely design/demo content and not a first-class brand CRUD experience. Existing role path checks are in `src/routes/access.ts`; existing UI tests use Vitest and Testing Library. Empty/error patterns and shared styles exist, but analytics loading/export, chart, date picker and management lifecycle tests need adding.

## 7. Problems, integrity risks, and limitations

1. Public campaign list has weakly validated offset/limit/sort behavior and does not serve an owner-scoped brand management workflow.
2. Campaign updates and lifecycle transitions are fragmented; generic dictionaries and direct status setting risk invalid state changes. Need validated typed contracts, centralized transition rules, audit events and strict ownership.
3. Campaign `budget` currently acts as reward cap in Phase 5 but does not record spend. Treating it as actual spend or marketing cost would create false ROI.
4. Existing conversion analytics are conversion-centric/order-unique, while Phase 5 rewards and Phase 4 attribution are item-level. Mixed cart revenue/rewards must aggregate only correctly attributed `OrderItem`s and must not multiply conversion count/revenue through joins.
5. Payment is heterogeneous: COD pending orders are not confirmed revenue; Demo is a simulation, not cash revenue; legacy paid rows have unverified provenance. Separate these states in every summary.
6. The current campaign analytics rate is confirmed conversions / distinct visitors. Click-based and visitor-based rates require explicit numerator/denominator and nonzero denominator handling.
7. Click counters duplicate event data and can drift; analytics should use valid click rows, not sum both sources.
8. Existing date filters are relative-duration-only and differ across APIs. Need validated UTC half-open timestamp bounds, deterministic presets, future/empty/reversed range behavior, and an explicit campaign-lifetime interpretation.
9. Reward snapshots are historical evidence; analytics must distinguish simulated reward value, liability states, reversed rewards and memo-only simulated payout entries. Do not call an approved reward a paid payout.
10. No source contains recorded marketing costs; ROI and cost-per-conversion are unavailable, not zero, until actual campaign expense data is supported.
11. Current route/UI separation is a large monolith; incremental components and existing models/services are preferable to duplicate campaign/analytics systems.
12. Existing SQLite tests do not prove PostgreSQL query behavior, production volumes, browser behavior, privacy/legal review or concurrent writes.

## 8. Phase 6 implementation plan

1. Keep existing Campaign/Product/Application/Referral/Conversion/Order/OrderItem/Reward/Ledger models. Add a small additive, audit-friendly campaign configuration/metrics contract only if a meaningful requested field is not representable; do not use a campaign budget as spent cost.
2. Implement typed, owner-scoped brand campaign list/create/edit/detail and status actions with validated transition map, filters, sort, bounded page size and audit logging. Preserve public discovery and Phase 1–5 behavior.
3. Add a centralized analytics service using SQL-scoped queries and Decimal-safe amounts. Reuse Phase 4 attribution logic and Phase 5 reward/ledger lifecycle; ensure item-level revenue, payment/reversal separation, distinct visitors and deduplicated order conversions.
4. Add authenticated brand overview, campaign detail analytics, creator comparison, product performance, trend/funnel, export and admin-only platform aggregate routes. Server-validate dates/filters and campaign/product/creator ownership; never return customer identifiers/contact/address.
5. Define shared metric names/formulas and truthful unavailable ROI contract. Insights are deterministic threshold-based observations with transparent criteria, not AI claims.
6. Add a role-gated responsive management/analytics area using existing React Query, Recharts, styles and API helpers; implement loading/error/empty states, date/campaign filters, sortable paginated tables and formula-aware CSV export.
7. Add backend lifecycle, aggregation, date, role/privacy, mixed-cart, COD/demo, ROI-unavailable, CSV-injection and integration tests; frontend rendering/filter/chart/export/role tests; update status, roadmap and Phase 6 implementation documentation.
8. Run all backend/frontend/migration checks, security/dependency checks where available, inspect the patch, commit logical milestones and push only to the existing active branch. PostgreSQL/browser/production limitations must be stated rather than implied verified.
