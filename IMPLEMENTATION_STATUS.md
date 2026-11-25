# CROWND implementation status

Updated: 2026-11-25, after source audit and Phase 1 authentication/security work. This checklist is conservative: checked items are implemented and the indicated tests passed; not checked means incomplete or unverified. Detailed task/dependency plan: [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

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

## In progress / partial

- [ ] Auth is significantly safer but not independently security-audited. Rate limit is IP-based; no MFA, persistent login-failure scoring, account lockout, device/session listing, signed email provider callbacks, or session-management UI.
- [ ] SMTP adapter is implemented but no external provider credentials/delivery reputation are configured. Actual external receipt was not tested. Compose Mailpit is local-only.
- [ ] Cookie origin forwarding requires exact production `CORS_ORIGINS`, `FRONTEND_BASE_URL`, and trusted reverse-proxy configuration; only test-client and local proxy behavior were tested.
- [ ] Frontend navigation now gates roles, but the application remains a large `App.tsx`; numerous feature controls still have incomplete functionality.
- [ ] Existing campaign/application/referral/order flows remain partial; older business routes use generic dictionaries and need typed schemas and broader cross-resource ownership tests (Phase 2).
- [ ] Orders are single-product guest requests with manual code attribution. Payment simulator is not a verified provider and must never run in production.
- [ ] Rewards start pending; automatic eligibility, refund reversal, admin approval, balanced ledger and payout settlement are absent.
- [ ] Dashboards have basic aggregate queries; full filters, role customer workflows and transactional analytics are absent. Sample discovery fallback demo campaign cards remain labeled `DEMO`.

## Not started

- [ ] Complete API Pydantic schemas, centralized policy layer and full cross-brand/creator/customer privacy/ownership audit.
- [ ] Persistent multi-item cart, customer addresses, shipping/tax, inventory reservations and complete fulfillment.
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

## Remaining known risks / required configuration

- Production needs `APP_ENV=production`, strong unique `JWT_SECRET`, PostgreSQL `DATABASE_URL`, `COOKIE_SECURE=true`, `FRONTEND_BASE_URL`, exact HTTPS `CORS_ORIGINS`, explicit trusted proxy networks, Redis `RATE_LIMIT_STORAGE_URI`, `EMAIL_MODE=smtp`, SMTP host/port/credentials/TLS/from address. App rejects unsafe defaults in production.
- `EMAIL_MODE=disabled` is safe but means no verification/reset email is sent and new accounts cannot log in until SMTP is configured. The local Compose Mailpit sink is not an external sender.
- Never deploy with `APP_ENV=development`, `PAYMENT_MODE=simulator`, default JWT key, demo seed credentials, or memory-only rate limits.
- Existing initial migration `0001` dynamically invokes current ORM metadata; `0002` is conditional to accommodate that history. Validate backups and reviewed upgrade/rollback on a copy of each external database before deployment.
- No live payment provider, production payout rail, external email account or managed production service is configured. CROWND is not production-ready.
