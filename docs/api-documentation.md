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

## Existing product endpoints

| Method/path | Access | Behavior |
|---|---|---|
| GET `/health` | Public | API health. |
| GET `/creators` | Auth | Search/filter creator list. PUT `/creators/me` updates creator basics. |
| GET/POST `/products` | Public read / brand write | List active items; create product. |
| GET/POST `/campaigns` | Public listing / brand create | Browse/create draft campaign. GET `/campaigns/{id}`; PATCH `/campaigns/{id}/status` is owner/admin guarded. |
| POST `/campaigns/{id}/applications` | Creator | Apply once to published campaign. GET `/applications`; PATCH `/applications/{id}` for campaign owner/admin review. |
| GET `/referrals/me` | Creator | Referral links after acceptance. GET `/r/{code}` records a click and returns destination metadata. |
| POST `/orders` | Public checkout API | Single-product order; explicit referral code validation. `simulate_payment: true` only in development simulator configuration. |
| GET `/orders` | Auth | Orders filtered by customer email, brand product ownership, creator referral, or admin. |
| GET `/rewards/me`, POST `/payouts` | Creator | Reward list and threshold-checked payout request. |
| GET `/analytics/overview`, `/analytics/timeseries` | Auth | Database-derived role-scoped counts and paid revenue. |
| GET `/ai/matches/{campaign_id}` | Brand owner/admin | Deterministic weighted match explanations. |
| GET `/admin/users`, `/admin/audit-logs` | Admin | Basic administrative read endpoints. |

JSON errors use FastAPI `{ "detail": ... }`; input schemas enforce auth fields and basic validation. Most older business writes still use generic dictionaries and are listed for Phase 2 hardening in `DEVELOPMENT_ROADMAP.md`.
