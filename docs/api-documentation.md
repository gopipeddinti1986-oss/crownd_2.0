# API overview

Base path: `/api/v1`. Interactive OpenAPI: `/docs`. Protected API requests use `Authorization: Bearer <short-lived-access-token>`. Browser refresh credentials are sent only as an HttpOnly cookie; never read/copy one in frontend code.

## Authentication endpoints

| Method/path | Access | Behavior |
|---|---|---|
| POST `/auth/register` | Public, throttled | Validates and creates creator/brand/customer account as unverified; returns 202 and does not issue a token. Email is attempted only through configured provider. |
| POST `/auth/login` | Public, throttled | Validates credentials/verification; returns short-lived `access_token` + user and sets refresh cookie (not in JSON). |
| POST `/auth/refresh` | Refresh cookie + trusted origin, throttled | Rotates refresh credential, returns new access token and user. Invalid/replayed/expired sessions are rejected. |
| POST `/auth/logout` | Access token + trusted origin | Revokes current session and clears refresh cookie (204). |
| POST `/auth/logout-all` | Access token + trusted origin | Revokes every session for current user (204). |
| GET `/auth/me` | Access token | Current DB-backed user and safe profile fields. |
| POST `/auth/email/verification/request` | Public, throttled | Requests a fresh verification link with non-enumerating response. |
| POST `/auth/email/verification/confirm` | Public, throttled | Consumes one valid verification token; links are single-use/expiry-limited. |
| POST `/auth/password/reset/request` | Public, throttled | Non-enumerating reset request. |
| POST `/auth/password/reset/confirm` | Public, throttled | Consumes one reset token, sets a new password and revokes all sessions. |

Auth errors use stable HTTP statuses with safe detail; refresh/login are `no-store`. Rate-limit rejection returns 429. `Origin` checks apply to refresh/logout cookie operations. SMTP disabled responses explicitly say no email was sent. Configure SMTP; do not pass auth tokens in query strings (email templates use fragments).

## Customer commerce endpoints

| Method/path | Access | Behavior |
|---|---|---|
| GET `/products` | Public | Search/filter/sort and page catalog records. Price and stock are current database values. |
| GET `/products/categories`, `/products/brands` | Public | Catalog filter options. |
| GET `/products/{product_id}` | Public | Product description, image gallery, specifications, regular/discounted price, brand, availability, related products and active creator program. |
| GET `/cart` | Authenticated | Read this account's persisted cart with recalculated lines/totals and signed referral attribution. |
| POST `/cart/items` | Authenticated, throttled | `{product_id, quantity}` adds to the account cart after active/stock checks. Prices and totals are never accepted. |
| PATCH `/cart/items/{item_id}` | Authenticated, throttled | Set quantity for an item belonging to the current account; stock is validated. |
| DELETE `/cart/items/{item_id}`, DELETE `/cart` | Authenticated | Remove one item or empty the current account cart. |
| POST `/checkout` | Authenticated, throttled | Requires `Idempotency-Key` header and validated `shipping_address`; creates one multi-item order from the server cart, calculates fixed-precision totals from live DB prices, conditionally decrements stock in one transaction and snapshots order lines/address/referral. Same owner/key returns the prior order rather than charging/creating twice. |
| GET `/orders?view=customer` | Authenticated | Paginated customer-owned history for any signed-in role; customer role defaults to its own records. `view=business` preserves the existing brand/creator/admin reporting scope. |
| GET `/orders/{public_order_id}` | Owner / associated brand or creator / admin | Order detail, item snapshots, status, payment status and address only for customer/admin. Cross-user misses return 404. |
| POST `/orders/{public_order_id}/cancel` | Customer owner | Cancels only unpaid pending/confirmed orders and restores reserved stock transactionally. Paid orders require a real refund workflow and cannot use this endpoint. |
| PATCH `/orders/{public_order_id}/status` | Associated brand/admin | Validates `pending → confirmed → processing → shipped → delivered`; fulfillment beyond confirmation requires `payment_status=paid` set by a trusted provider (not currently integrated). |
| GET `/r/{referral_code}` | Public | Preserves existing click tracking, validates active creator/campaign and sets a signed, HttpOnly, attribution-window cookie. The SPA `/r/{code}` landing route uses this API and navigates to the product/shop. Checkout accepts attribution from that cookie only, not a caller-supplied creator ID/code. |

Cart persistence is **account-only**; there is no guest cart or merge. There are no saved-address book, shipping/tax calculation, coupon system, or payment-provider callback. Checkout currently uses zero/free shipping, supports product `sale_price`, reserves/decrements stock on order creation, and leaves payment/order `pending`. No real payment is collected. Because no provider can confirm payment/failure yet, an order can remain pending indefinitely unless the customer cancels it; operations must not treat it as paid. A signed referral is valid for the configured `ATTRIBUTION_DAYS` window and must match active creator/campaign and compatible product(s).

## Existing product endpoints

| Method/path | Access | Behavior |
|---|---|---|
| GET `/health` | Public | API health. |
| GET `/creators` | Auth | Search/filter creator list. PUT `/creators/me` updates creator basics. |
| GET `/products` | Public | Search active products (`q`, `category`, `brand_id`, `min_price`, `max_price`, `in_stock`); sort (`newest`, `price_asc`, `price_desc`, `name`) and paginate (`page`, `page_size`). Returns `{items,total,page,page_size,pages}` with database-derived prices/stock and brand data. |
| GET `/products/categories`, `/products/brands` | Public | Filter values derived from currently active catalog items. |
| GET `/products/{product_id}` | Public | Product detail, gallery/specifications, stock and discount, brand, related products, creator program and current valid attribution. |
| POST `/products` | Brand | Create a product with validated price/sale price, stock, images and specifications. |
| GET/POST `/campaigns` | Public listing / brand create | Browse/create draft campaign. GET `/campaigns/{id}`; PATCH `/campaigns/{id}/status` is owner/admin guarded. |
| POST `/campaigns/{id}/applications` | Creator | Apply once to published campaign. GET `/applications`; PATCH `/applications/{id}` for campaign owner/admin review. |
| GET `/referrals/me` | Creator | Referral links after acceptance. GET `/r/{code}` records a click, sets the signed attribution cookie and returns destination metadata. |
| POST `/orders` | Legacy public endpoint | Single-product compatibility flow with explicit validated referral code. New storefronts use authenticated `/cart` + `/checkout`. `simulate_payment: true` remains development simulator only. |
| GET `/orders` | Auth | Business reporting by brand/creator/admin; pass `view=customer` for the current account's customer order history. |
| GET `/rewards/me`, POST `/payouts` | Creator | Reward list and threshold-checked payout request. |
| GET `/analytics/overview`, `/analytics/timeseries` | Auth | Database-derived role-scoped counts and paid revenue. |
| GET `/ai/matches/{campaign_id}` | Brand owner/admin | Deterministic weighted match explanations. |
| GET `/admin/users`, `/admin/audit-logs` | Admin | Basic administrative read endpoints. |

JSON errors use FastAPI `{ "detail": ... }`; input schemas enforce auth fields and basic validation. Most older business writes still use generic dictionaries and are listed for Phase 2 hardening in `DEVELOPMENT_ROADMAP.md`.
