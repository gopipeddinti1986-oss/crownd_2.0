# CROWND implementation status

Updated: 2026-11-25, after Phase 2 customer-commerce implementation and verification. This checklist is conservative: checked items are implemented and the indicated tests passed; not checked means incomplete or unverified. Detailed task/dependency plan: [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

## Verified audit baseline

- Existing branch began clean at commit `75601c8` on `arena/e6c9b4f7-crownd-2-0`; remote is the requested GitHub repository. Existing Vite preview/API were running and UI, API health and campaigns returned 200 before changes.
- Baseline: backend pytest **4 passed**; frontend lint clean, Vitest **3 passed**, TypeScript/Vite production build passed (existing >500 kB JS warning).
- Audit confirmed localStorage bearer token storage, no refresh/revocation, immediate login before email verification, custom PBKDF2 password hashes, no auth rate limits/password reset/verification, generic input dictionaries, app-import `create_all`, incomplete business workflows and a dev-only simulator. Expanded findings are in the roadmap.

## Completed and verified

### Existing product foundation (preserved)

- [x] React/TypeScript/Vite marketing site and responsive dashboard; TanStack Query, Recharts, Lucide.
- [x] FastAPI v1 API, SQLAlchemy models, SQLite/PostgreSQL URL support, Alembic, Docker/Compose.
- [x] Creator/brand/customer registration roles; profiles; products/campaigns/applications/referrals/orders/rewards/analytics basics.
- [x] Creator matching uses deterministic weighted rules and explains factors.
- [x] Payment success can only be simulated with `APP_ENV=development` and `PAYMENT_MODE=simulator`; it is not real payment processing.

### Phase 1 — authentication and security

- [x] Verified full repository/API/schema/frontend/auth/test/docs baseline before coding; updated this phased roadmap first.
- [x] New password hashes use Argon2id through `pwdlib`; legacy PBKDF2 accounts can sign in and upgrade transparently.
- [x] Pydantic auth schemas validate email, password length (12 minimum for new/reset passwords), role allowlist, sizes and extra fields.
- [x] Signup no longer creates a signed-in session; new accounts remain unverified; admin self-registration is unavailable; registration response avoids duplicate-email account enumeration.
- [x] One-use purpose-specific email verification and password-reset token hashes, expiration, replay rejection and existing-session revocation after password reset.
- [x] SMTP provider abstraction; `EMAIL_MODE=disabled` does not send or log token content and is explicit in API/UI. SMTP errors/logs are redacted. Docker Compose includes local Mailpit sink (not external delivery).
- [x] 15-minute default access JWTs bind to a persistent auth session; every protected request validates live session, user state and role from DB.
- [x] HMAC-bound, opaque refresh token is set only as HttpOnly, narrow-path, SameSite=Lax cookie; only its digest is persisted. Refresh rotates; genuine old-token replay revokes session; arbitrary forged refresh token cannot revoke another session.
- [x] Current-session logout and logout-all revoke server-side sessions; reset revokes sessions. Existing JWTs are invalidated immediately via DB session check.
- [x] Frontend stores access tokens in JavaScript memory only; startup restores via refresh cookie; 401 triggers a single refresh; expiry clears user state and protected paths show auth; navigation/page guards are role-aware.
- [x] Auth endpoint rate limits, HMAC-obscured IP keys, explicitly trusted proxy forwarding, trusted `Origin` validation on cookie endpoints, secure response headers, no-store auth responses, generic unexpected errors and sanitized logs.
- [x] Production configuration rejects weak/default secret, insecure cookies, wildcard/non-HTTPS/mismatched origins, memory-only/disabled rate limiting, disabled SMTP, non-TLS SMTP and SQLite.
- [x] Additive migration `0002_auth_security`; app no longer executes `Base.metadata.create_all()` on import. Old existing accounts receive compatibility `email_verified=true` during migration; new signups explicitly false.

### Phase 2 — Customer commerce

- [x] API-backed public product discovery with full-text-like name/description/category/brand search, category and brand filters, effective-price range, stock filter, sort and page controls; active brand, stock and availability shown.
- [x] Product detail includes regular/sale pricing, images/gallery, specifications, brand, stock, creator program, referral context and related products. Product-create validation supports sale price, gallery and specs.
- [x] Authenticated server-persisted carts support add/set quantity/remove/clear. Cart/order prices are always recomputed from database Decimal values; client amounts are rejected by the checkout schema.
- [x] Authenticated multi-line checkout validates a shipping address and cart state, uses a required idempotency key, snapshots item/brand/price/address data, writes order and items together, and conditionally decrements inventory inside one transaction.
- [x] Customer order history/details expose only owned records (404 for cross-user access); brand/creator/admin business order views remain available. Valid unpaid pending/confirmed cancellation restores stock once; invalid transitions, repeated cancellation, and fulfillment before trusted paid status are rejected.
- [x] Existing referral-code route sets a signed HttpOnly referral-window cookie. Checkout rechecks active creator/campaign/product eligibility and stores the existing `referral_id`; caller-supplied referral IDs/codes are not accepted by the new checkout.
- [x] `/shop`, product details, `/cart`, `/checkout`, `/orders`, and order detail pages use the real API and existing CROWND styling; frontend component tests cover discovery, filters including in-stock, empty/error states, product detail/add, cart update/remove, checkout and order history/detail.
- [x] Additive migration `0003_customer_commerce` adds optional discount/gallery/specification fields, cart/cart-item tables, order-item snapshots, customer/idempotency/address metadata; rollback and fresh/existing SQLite paths passed.

## In progress / partial

- [ ] Auth is significantly safer but not independently security-audited. Rate limit is IP-based; no MFA, persistent login-failure scoring, account lockout, device/session listing, signed email provider callbacks, or session-management UI.
- [ ] SMTP adapter is implemented but no external provider credentials/delivery reputation are configured. Actual external receipt was not tested. Compose Mailpit is local-only.
- [ ] Cookie origin forwarding requires exact production `CORS_ORIGINS`, `FRONTEND_BASE_URL`, and trusted reverse-proxy configuration; only test-client and local proxy behavior were tested.
- [ ] Frontend navigation now gates roles, but the application remains a large `App.tsx`; numerous feature controls still have incomplete functionality.
- [ ] Existing campaign/application/referral and legacy business writes remain partial; older routes use generic dictionaries and need typed schemas and broader cross-resource ownership tests (API-boundary hardening phase).
- [ ] Legacy public `POST /orders` remains a single-product compatibility endpoint. New `/checkout` requires a signed-in account; guest carts and cart merge are intentionally unsupported.
- [ ] Checkout creates pending orders, reserves inventory, and reports zero/free shipping. No payment provider, verified payment events, payment-failure cleanup, coupon, tax/shipping quote, address book, or pending-order expiry exists. Do not treat pending orders as paid or fulfill them.
- [ ] SQLite stock contention tests cover stale-cart oversell prevention and atomic conditional updates; a multi-process/PostgreSQL concurrency/load stress test has not been run.
- [ ] Rewards start pending; automatic eligibility, refund reversal, admin approval, balanced ledger and payout settlement are absent.
- [ ] Dashboards have basic aggregate queries; full filters, role customer workflows and transactional analytics are absent. Sample discovery fallback demo campaign cards remain labeled `DEMO`.

## Not started

- [ ] Complete API Pydantic schemas, centralized policy layer and full cross-brand/creator/customer privacy/ownership audit.
- [ ] Payment provider integration/signature webhooks, order payment-failure/refund workflows, saved address book, shipping/tax quoting, automatic expiry of unpaid inventory reservations and complete fulfillment operations.
- [ ] Razorpay test adapter, signature verification, signed idempotent webhooks, refunds/chargebacks.
- [ ] Reward lifecycle worker and immutable balanced ledger, payout admin approval/reconciliation.
- [ ] Complete creator/brand profiles, social evidence, portfolio uploads, brand verification, invitations/collaboration/deliverables.
- [ ] Messaging, persisted notifications and production email preferences/delivery monitoring.
- [ ] Admin bootstrap and full admin controls/risk/disputes/audit history beyond basic list endpoints.
- [ ] Redis included/managed for production deployment; production secret manager, TLS, backups, observability and hardened runtime.
- [ ] Playwright end-to-end workflows, multi-worker/security/load testing, independent security review and CI release gates.

## Test/build record for this update

- Backend `backend/.venv/bin/pytest -q`: **19 passed**, 1 Starlette/httpx deprecation warning. Coverage includes registration, Argon2id, legacy rehash, unverified login, invalid credentials, JWT/session expiry, refresh-cookie attributes/rotation/replay/forged token handling, logout/logout-all, reset expiry/replay/session revocation, email verification expiry/replay, role and ownership denials, origin validation, rate limiting, fail-closed production config, disabled email behavior, plus existing campaign/referral/order/reward and Decimal workflows.
- Backend `.venv/bin/alembic upgrade head`: passed against local DB at revision 0002; fresh and simulated pre-existing `0001_initial` SQLite upgrade paths both passed. Python `compileall`: passed. PostgreSQL migration and rollback on a production-like copy remain unverified.
- Live API smoke passed using seeded `brand@crownd.example.com`: login, HttpOnly refresh-cookie attributes, `/me`, refresh rotation, logout and access-token revocation. Demo password is `CrownDemo!2026` (local development only). Seed output and README now use reserved `.example.com` addresses rather than invalid `.local` email domains.
- Frontend `npm run lint`: passed with no warnings. `npm test`: **12 passed**. `npx tsc -b` and `npm run build`: passed.
- `npm audit --audit-level=moderate`: **0 vulnerabilities**. `git diff --check` passed; secret-pattern scan found no credentials (only placeholder keys in `.env.example`).
- Build warning remains: main JS chunk ~709 kB uncompressed (>500 kB advisory). Frontend auth tests use mocked Axios adapters; no browser E2E test yet. Compose could not be validated because Docker is not installed.

### Phase 2 verification

- Backend `.venv/bin/pytest -q`: **27 passed**, 1 existing Starlette/httpx deprecation warning. New commerce tests cover product search/brand/category/price/availability/pagination/detail, sale-price/stock validation, persistent cart ownership/quantity/price fields, checkout total recomputation/idempotency/order lines/address, stale stock/oversell protection, cancellation restoration/replay, order history/detail cross-user denial, lifecycle transitions, legacy business-list response compatibility and signed referral cookie tamper/attribution.
- Migration `0003_customer_commerce`: fresh SQLite upgrade, existing pre-commerce `0002` SQLite schema upgrade and upgrade/downgrade/re-upgrade cycle passed. Current local Alembic head is `0003_customer_commerce`. PostgreSQL migration/rollback was not tested.
- Live preview smoke: `/shop`, proxied product catalog/categories and a product-detail request returned HTTP 200 from the seeded local catalog. No live checkout was placed against the shared demo DB.
- Frontend `npm run lint`: clean. Vitest: **21 passed** including 7 commerce component/UI tests plus a customer-role registration/verification test. Coverage includes product discovery, empty/error states, product detail/add, cart update/remove, checkout, orders/cancellation and paise-accurate prices. TypeScript check and Vite production build passed. `npm audit --audit-level=moderate`: **0 vulnerabilities**.
- Production bundle is ~743 kB uncompressed (>500 kB advisory). No browser-based E2E journey or actual multi-process concurrency stress test was run.

## Remaining known risks / required configuration

- Production needs `APP_ENV=production`, strong unique `JWT_SECRET`, PostgreSQL `DATABASE_URL`, `COOKIE_SECURE=true`, `FRONTEND_BASE_URL`, exact HTTPS `CORS_ORIGINS`, explicit trusted proxy networks, Redis `RATE_LIMIT_STORAGE_URI`, `EMAIL_MODE=smtp`, SMTP host/port/credentials/TLS/from address. App rejects unsafe defaults in production.
- `EMAIL_MODE=disabled` is safe but means no verification/reset email is sent and new accounts cannot log in until SMTP is configured. The local Compose Mailpit sink is not an external sender.
- Never deploy with `APP_ENV=development`, `PAYMENT_MODE=simulator`, default JWT key, demo seed credentials, or memory-only rate limits.
- Existing initial migration `0001` dynamically invokes current ORM metadata; `0002` is conditional to accommodate that history. Validate backups and reviewed upgrade/rollback on a copy of each external database before deployment.
- No live payment provider, production payout rail, external email account or managed production service is configured. CROWND is not production-ready.
