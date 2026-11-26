# Phase 8 — Notifications, communication and workflow automation

**Status:** implemented locally; not a production-readiness or independent security-review claim.
**Migration:** `0009_notifications` (after `0008_platform_admin`).
**Audit and design plan:** [`PHASE_8_NOTIFICATIONS_AUDIT.md`](PHASE_8_NOTIFICATIONS_AUDIT.md).

## Design

Phase 8 extends the existing FastAPI/SQLAlchemy/React modular monolith and SMTP abstraction. It adds no second identity, order, campaign or reward system and no Redis/Celery/Kafka/RabbitMQ dependency.

- **Inbox:** `notifications` stores bounded text, recipient, category, read timestamp, optional allowlisted in-app route and a unique `(recipient_id, event_key)`. Inserts share the existing business transaction. Current APIs only select/update by the authenticated user ID; list responses are paginated (maximum 100 per page).
- **Preferences:** one row per user stores global inbox/email defaults and per-category overrides for `order`, `campaign`, `application`, `reward`, `security`, and `account`. Essential verification/reset and critical account-security emails bypass routine email opt-outs; corresponding in-app alerts still follow inbox preferences. Account recovery remains generic and does not reveal whether an email exists.
- **Email outbox:** `email_deliveries` stores recipient ID, event key/category, attempt/status/timing and Fernet-authenticated ciphertext for subject/body. It does not duplicate email addresses, tokens, plaintext or provider response text into monitoring records. Verification/reset links remain in URL fragments, are one-use, and are encrypted while queued.
- **Encryption key:** Fernet key material is derived from the configured `JWT_SECRET`. API and worker must use the same secret. Rotating it with pending rows makes those rows undecryptable; drain or safely resolve pending deliveries before rotation. A dedicated key-management/rotation scheme is a production follow-up.
- **Worker:** `python -m app.worker` polls SQL; `--once` drains currently due rows, `--batch-size` is bounded to 1–100 and default polling is five seconds. SMTP runs only in this separate process, never in business API requests. Failures use static error codes and bounded exponential backoff (60s, 5m, 15m, 1h) for at most five attempts. Stale `sending` rows older than ten minutes are made eligible again.
- **Delivery semantics:** at least once. If SMTP accepts a message and the worker crashes before recording acceptance, a duplicate can occur. `sent` means only that the configured provider accepted the message, not inbox receipt. Disabled email is stored as `suppressed`; it is never reported as sent. The worker has no heartbeat, so operations report `worker_status: not_measured`, not healthy.
- **Concurrency:** the worker uses a conditional database claim and durable `sending` state. SQLite tests do not prove multi-process safety, and no PostgreSQL contention test has been run. Operate a single worker until concurrency/load behavior is verified.
- **Privacy/safety:** admin telemetry is admin-only and returns queue category/status/times/attempts/static error codes, never recipient IDs/emails, message body/ciphertext or tokens. Notification actions are limited to selected relative app routes; email headers reject control characters. Mail is plain text. React renders notification content as text, not HTML.

## Event coverage

| Existing event boundary | Recipient-facing message semantics |
|---|---|
| Auth registration, verification request and password reset request | One-use email queued transactionally; generic responses preserved. No raw token in logs, admin telemetry or plaintext outbox. Verification completion creates an account notice; password-reset completion and refresh-token reuse detection queue essential security notices. |
| Authenticated checkout | COD says no payment was collected and collection is recorded only after delivery. Demo success/failure explicitly says simulated/no real money charged or transferred. |
| Order cancellation, admin status update and COD collection | States that CROWND's order status was changed; explicitly discloses no refund, no carrier tracking, or no digital transaction where relevant. |
| Campaign application submission and review | Notifies campaign brand and applicant of application status; no private risk/dispute details included. |
| Admin campaign moderation and account suspension/reactivation | Notifies affected account without exposing internal admin reason. Essential account-security mail can bypass preferences. |
| Reward record creation, admin review and simulated payout record | Describes the platform ledger/status only; simulated payout explicitly says no actual money transferred. |

Risk-flag/dispute detail and customer contact/address data are not sent. Product/cart edits, ordinary sign-in failures and internal admin-audit records do not generate user-facing messages.

## API surface

- `GET /api/v1/notifications?page=&page_size=&unread_only=` — own inbox, total/pages and unread count.
- `PATCH /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/read-all` — own records only; foreign IDs return 404.
- `GET/PUT /api/v1/notifications/preferences` — global defaults and category channel overrides.
- `GET /api/v1/admin/notification-deliveries/summary` — admin-only status counts, SMTP configuration state, latest queue time and explicitly unmeasured worker status.
- `GET /api/v1/admin/notification-deliveries?page=&page_size=&status=&category=` — admin-only redacted, bounded queue list.

Frontend routes: `/notifications`, `/settings/notifications`, and admin-only `/admin/notifications`. The authenticated shell has an unread-count bell badge. Phase 7 operations overview shows outbox availability, provider configuration and unmeasured worker state separately.

## Operation

- Local process: run API and `python -m app.worker` with the same `DATABASE_URL`, `JWT_SECRET`, `EMAIL_MODE`, and SMTP settings. `backend/.env.example` documents the current configuration.
- Compose: `docker compose up --build` starts the distinct `notification-worker` service. Mailpit is optional (`--profile dev-mail`) and loopback-only; the default Compose email mode is disabled. Mailpit is not an external sender.
- With `EMAIL_MODE=disabled`, the worker marks due rows `suppressed` (`provider_disabled`) and no mail is sent. New accounts cannot verify/login until email is configured. With SMTP configured but no worker, outbox rows remain pending.
- Admin delivery monitor is telemetry, not a resend tool or provider health probe. It cannot confirm inbox receipt, bounces or external SMTP availability.

## Verification and remaining limitations

Final local checks on the implementation tree:

- Backend: `backend/.venv/bin/pytest -q` — **66 passed**, one existing Starlette/httpx `TestClient` deprecation warning. `python -m compileall -q app tests` passed. Coverage includes notification migration/up-regrade, API ownership/read-state/pagination/preferences, idempotency, safe paths/header validation, encrypted action-link queueing, provider-disabled suppression, retry/backoff/five-attempt cap, redacted admin monitor and business event integration.
- Frontend: `npx tsc -b`, `npm run lint`, Vitest — **9 files / 38 tests passed**, and `npm run build` passed. Existing Recharts jsdom zero-size warnings remain; build reports the main minified chunk at about **864.17 kB** (>500 kB advisory).
- `git diff --check` passed. SQLite fresh and historical Phase 8 migration upgrade/re-upgrade paths are covered by tests.
- Docker Compose syntax/startup was not verified because Docker is not installed in this environment. SMTP is not configured for this run; tests use a fake provider and no real inbox receipt was tested.

PostgreSQL migration/runtime/concurrency, live SMTP/inbox delivery, browser E2E/accessibility, independent security review, production worker liveness and multi-worker load are not claimed. No real payment, payout, refund or shipping integration exists; notification copy explicitly preserves the current demo/COD/manual fulfillment semantics.
