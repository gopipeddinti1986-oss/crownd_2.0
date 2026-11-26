# Security guide

## Implemented controls

- Argon2id password hashes via maintained `pwdlib`; legacy PBKDF2 hashes are verified and upgraded after a successful sign-in.
- Pydantic auth request schemas enforce email/password/role/string bounds and reject unexpected fields. Admin self-registration is prohibited.
- Short-lived JWT access tokens are held in frontend module memory, not Web Storage. Each token is bound to a persistent server session; protected requests check account/session state so logout/reset revocation takes effect immediately.
- High-entropy opaque refresh token is HMAC-bound to its session. Only a SHA-256 digest is stored; `HttpOnly; SameSite=Lax`, narrow-path cookie is `Secure` in production. Rotation replay revokes the session; unauthentic forged cookies do not revoke another session. Current session and all-session logout are implemented.
- One-use, purpose-separated, expiring Argon-independent random email-action tokens are hashed in the database. Reset is enumeration-safe and revokes every active session.
- SlowAPI request limits cover sensitive auth endpoints. IP keys are HMACed; forwarded client addresses are accepted only from explicit trusted proxy peers/networks. Production refuses memory-only/disabled limiter configuration.
- Cookie endpoints enforce trusted `Origin`; CORS is credentialed but explicitly allowlisted. Production rejects weak/default JWT secrets, insecure cookies, wildcard/non-HTTPS origins, mismatched frontend origin, disabled email, non-TLS SMTP and SQLite.
- Auth responses use `Cache-Control: no-store`; unexpected errors return a generic body and safe logs contain only exception type and route path. Email delivery errors omit recipient, message, SMTP response and token. Email token URLs place credentials in URL fragments, not query parameters.
- ORM parameterization, role dependencies and existing route ownership checks remain active.

## Configure production

Set `APP_ENV=production`, a unique 32+ character high-entropy `JWT_SECRET`, managed PostgreSQL `DATABASE_URL`, `COOKIE_SECURE=true`, exact HTTPS `FRONTEND_BASE_URL` included in `CORS_ORIGINS`, explicit trusted proxy IP/network(s), a reachable Redis URI in `RATE_LIMIT_STORAGE_URI`, `EMAIL_MODE=smtp`, TLS-enabled SMTP host/port and credentials (`SMTP_HOST`, `SMTP_PORT`, optional `SMTP_USERNAME`/`SMTP_PASSWORD`, `SMTP_STARTTLS=true`, `EMAIL_FROM`). Configure HTTPS/reverse-proxy forwarding; each trusted proxy must overwrite (not append to client-controlled) forwarded client IP/host headers, and only the immediate proxy peer may be trusted. No external credentials are needed in chat; configure secrets in the deployment secret manager.

For local development, `EMAIL_MODE=disabled` is the safe no-send default and returns an explicit no-email message. The Compose Mailpit sink (SMTP at 1025, inbox at 8025) is local-only and not a production email service. The memory limiter is single-process development only.

## Known gaps and release blockers

No MFA, full brute-force/credential-stuffing protection, progressive account lock, session inventory/device revocation UI, signed email provider webhooks, CSRF token for cross-site cookie deployments beyond SameSite + Origin validation, independent security audit, privacy retention/deletion program, security monitoring, full schema validation outside auth payloads, or rate-limit failover test. Secrets manager, TLS, backups, Redis availability, SMTP delivery/reputation and trusted proxy configuration require operational controls. Demo Payment is an in-process simulation only and is not a financial transaction; COD collection is an administrator-attested offline event. Online payment is disabled. There is no provider signature/webhook/refund protection because no provider is connected. This is not a production-readiness claim.
