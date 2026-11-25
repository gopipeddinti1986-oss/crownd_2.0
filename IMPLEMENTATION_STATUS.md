# CROWND implementation status

Updated: 2026-11-25. This status is deliberately conservative; only checked items have working code and verification evidence. The source-verified audit and phased task plan are in [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

## Verified audit baseline

- Current branch began with a clean worktree at `75601c8`; existing web preview and API were running and returned HTTP 200 for UI, API health and campaigns.
- Baseline: backend pytest **4 passed**; frontend lint clean, Vitest **3 passed**, TypeScript/Vite production build passed (with existing >500 kB JS chunk warning).
- Source inspection found auth weaknesses: localStorage bearer JWT with no session/revocation, immediate auto-login before email verification, custom PBKDF2, no auth rate limit or reset/verification, generic dict write payloads, and weak default JWT secret. See roadmap for additional confirmed ownership/product/migration risks.

## Completed in this branch

- [x] Repo audit (initially README-only); frontend/backend structure and ignores.
- [x] React/TypeScript/Vite responsive marketing surface, creator/brand/admin workspace dashboard, campaign, creator, product, application, referral, earnings, analytics views; working auth forms; browser API client.
- [x] FastAPI versioned API, Swagger, CORS config, settings, SQLAlchemy relational schema, SQLite/PostgreSQL support, Alembic initial schema, Docker/Compose baseline.
- [x] Signup/login, PBKDF2 password hashing, signed access JWTs, active-account check, role dependencies, brand/creator profile creation/edit.
- [x] Product creation/listing; campaign draft creation, publication/pause/completion/cancel transitions and listing/detail.
- [x] Creator discovery and explainable weighted campaign matching; creator apply, duplicate protection, brand review, referral generation on acceptance.
- [x] Campaign-specific referral codes, click recording, published campaign/product validation, configurable 7-day attribution disclosure, simple order creation with stock decrement.
- [x] Development-only payment simulator gate; paid local order creates Decimal-based pending reward, cap checks and a pending ledger record.
- [x] Creator rewards view, payout request threshold and pending-request balance guard; brand/creator/admin overview and paid revenue timeseries from database.
- [x] Audit event table/basic event writes and admin audit/user list APIs.
- [x] Demo seed script and sample accounts clearly marked local-only.
- [x] Documentation for run, architecture, schema, auth, API, attribution, reward rules, testing, security, deployment, roadmap.

## In progress / partial

- [ ] Role-aware frontend navigation exists, but several routes are simplified views; customer shop/cart/checkout, complete brand/creator flows and admin management are not complete.
- [ ] Creator/brand profile coverage is partial; social links, audience demographics, portfolios, verification workflow, invitations and editing of full profiles remain.
- [ ] Referral endpoint records a click and returns attribution destination metadata; no browser cookie/session attribution through a real storefront yet. Order attribution currently requires explicit valid code.
- [ ] Payments are local simulation only. No gateway adapter, signed callback, webhook events, refunds, or payment idempotency.
- [ ] Rewards start pending; there is no worker to move to eligible, cancel/reverse refunds, administrative approval pipeline, robust double-entry ledger, or payout settlement integration.
- [ ] Matching is explainable weighted rules from available profile fields (not a trained ML model). Score fields currently exist but score history/component scoring is not implemented.
- [ ] Analytics use database-backed counts/revenue. Sample visuals in the public landing and non-data chart styling are illustrative, not claimed business metrics.
- [ ] Compose is a deployable local baseline, not a hardened production release; no CI pipeline, object storage, email provider, or deployed environment.

## Not started

- [ ] Refresh-token rotation/revocation, HTTP-only secure cookies, email verification, password reset, login throttling/rate limiting, CSRF protections.
- [ ] Customer account lifecycle and persistent multi-item cart, address/shipping/tax calculations, order status fulfillment.
- [ ] Real payment gateway (Razorpay), webhook verification, refund reconciliation.
- [ ] Background worker/queue, lifecycle tasks, durable notification/email delivery.
- [ ] Complete collaboration/deliverables and revision workflow, internal messaging.
- [ ] Full admin tools for brand verification, campaign moderation, risk/dispute review, reward approval, payout processing/settings.
- [ ] File/object uploads, S3-compatible adapter, user-facing account deactivation.
- [ ] Playwright end-to-end suite, frontend component tests, security tests/load tests, automated CI.

## Test/build record

- Backend: `backend/.venv/bin/pytest -q` — **4 passed** (signup/RBAC, campaign-application-referral-order-reward, duplicate application, Decimal reward math); Alembic initial migration and idempotent seed completed.
- Frontend: `npm test` — **3 passed**; `npm run lint` — clean; `npm run build` — passed on Vite 8 / React Router 7. `npm audit --audit-level=moderate` — **0 vulnerabilities**.
- Runtime smoke test: API `/health` returned ok and Vite proxy returned seeded campaign JSON.
- Known warning: frontend JavaScript bundle is about 703 kB before gzip (>500 kB warning); code splitting is future optimization. HTTPX/Starlette TestClient emits a deprecation warning.

## Known bugs / risks

- Demo user authorization is basic; admin user creation/bootstrap is not implemented.
- Local simulator success is intentionally not a production payment claim. Never deploy with `APP_ENV=development`/`PAYMENT_MODE=simulator`.
- Order endpoint is a deliberately small single-product API path and does not represent full checkout/payment verification.
- Initial Alembic revision creates schema from ORM metadata (review generated migrations for all future changes).
- Database startup currently invokes metadata creation for developer convenience; production operations should use reviewed migrations.
- JWT secret has a development fallback. Production deployment must provide a strong secret.

## External credentials / deployment

No external credentials are needed to run locally. Razorpay, email, object storage, managed PostgreSQL hosting, and production domain credentials are not wired; do not describe those as active. Required environment values for shared deployment: `DATABASE_URL`, strong `JWT_SECRET`, `APP_ENV=production`, CORS origins, and real `PAYMENT_MODE` adapter once implemented. A complete production rollout is not ready.
