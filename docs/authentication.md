# Authentication and account security

## Credentials and session flow

- New passwords use Argon2id via `pwdlib`. The login verifier supports the previous CROWND PBKDF2-SHA256 digest and upgrades a successful legacy login to Argon2id in the same transaction.
- Email and auth payloads use Pydantic validation. Self-registration supports creator, brand and customer only; `admin` cannot self-register.
- Registration does **not** log in the new account. It creates an unverified user and sends a one-use verification link only when an SMTP provider is explicitly configured and accepts the message.
- Login returns a short-lived JWT (default 15 minutes) in JSON and an opaque refresh credential only in an HttpOnly cookie. The cookie defaults to `SameSite=Lax`, `Path=/api/v1/auth`, and `Secure` in production. Cross-site API hosting may set `COOKIE_SAMESITE=none` only with `COOKIE_SECURE=true`; exact CORS and trusted-Origin allowlists remain mandatory. The refresh value is HMAC-bound to its session and only a SHA-256 digest is persisted.
- Refresh rotates its credential. A properly signed previously issued credential replay revokes the session; a random forged cookie cannot revoke a known session. Logout revokes the current session; logout-all and successful password reset revoke every session for the account.
- Access tokens include a session identifier and each protected request checks the live account/session row. Therefore logout and password reset revoke access tokens immediately, not only after JWT expiry.
- The SPA holds access tokens only in module memory. On reload, it calls the same-origin refresh endpoint and receives a new access token through the credentialed HttpOnly cookie. It never writes bearer tokens or user snapshots to localStorage. A protected 401 triggers one refresh attempt; failure clears in-memory state and presents sign-in.

## Email verification and recovery

One-use verification/password-reset tokens are random, purpose-scoped, expiry-limited and stored as hashes. Verification defaults to 24 hours; reset defaults to 30 minutes. Password reset responses do not disclose whether an email exists. A completed reset invalidates all login sessions. Tokens are sent in URL fragments (`#token=...`) so browsers do not include them in HTTP requests or routine access logs.

Email delivery is an adapter in `app/services/email.py`:

- `EMAIL_MODE=disabled` is the safe local default. The API queues encrypted action mail but no message is sent; the separate worker marks it suppressed and the API/UI state no email was sent. For configured SMTP delivery, run the Phase 8 worker with the same `JWT_SECRET`; see [`PHASE_8_NOTIFICATIONS.md`](PHASE_8_NOTIFICATIONS.md).
- `EMAIL_MODE=smtp` uses SMTP configuration. Provider errors are reduced to a generic operational error; logs omit address, body, credentials and token. Configure TLS for production.
- Docker Compose starts a local Mailpit SMTP sink and web inbox at port 8025; messages stay local and are not delivered to recipients.

## Throttling, origin and production requirements

SlowAPI applies per-client limits to register/login/refresh/logout/verification/reset. The limiter hashes client IPs in its storage keys and trusts `X-Forwarded-For` only from `TRUSTED_PROXY_IPS`. Production startup fails closed for a default/weak JWT secret, insecure cookie, wildcard/non-HTTPS/mismatched origins, disabled or in-memory-only limiter, disabled email, non-TLS SMTP or SQLite. Configure Redis-backed `RATE_LIMIT_STORAGE_URI` and the exact trusted proxy addresses/networks in production.

Cookie-auth endpoints validate `Origin`; direct same-origin SPA requests are accepted through configured origins, and trusted reverse proxies may supply the matching forwarded host. CORS remains explicit and credentialed. Auth responses are `Cache-Control: no-store`. Unknown failures return a generic error; safe server logs record only exception class and path, not URL query, request body, header or exception text.

## Limitations

There is not yet MFA, account recovery contact change, device/session listing UI, email verification deliverability monitoring, Redis service in the default compose file, or an external transactional email provider account. Production requires operators to supply SMTP and Redis services, secrets, TLS, backups and monitoring. Rate limiting is IP-based (not a full credential-stuffing defense), and the API is not independently security-audited.
