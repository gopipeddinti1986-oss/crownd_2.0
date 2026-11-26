# Phase 8 Notifications & Workflow Automation — Audit and Plan

**Audit date:** 2026-11-25

**Branch:** `arena/e6c9b4f7-crownd-2-0`

**Starting commit:** `13cd2aa33e10644bfbada6597241a940d56e6778`

**Audit scope:** existing API/business event boundaries, database and migration conventions, email/configuration, frontend navigation/API patterns, admin operations, and test setup. No implementation changes were made during the audit.

## Existing architecture

- FastAPI API composition is in `backend/app/api/v1/routes.py`; routers split authentication, commerce, campaigns, rewards, analytics, and administration. SQLAlchemy models live together in `backend/app/models/entities.py`; Alembic migrations are numbered through `0008_platform_admin`.
- `backend/app/services/email.py` already defines `OutgoingEmail`, an `EmailProvider` interface, SMTP delivery, and an explicit disabled provider. `settings.email_mode` is `disabled` or `smtp`; production configuration requires SMTP. Current auth verification and password-reset routes in `backend/app/api/v1/auth.py` call their email helper during the request, after persisting a one-use, hashed action token. The public responses are generic; URL tokens are placed in fragments; the helper avoids logging secrets.
- There is no persisted notification, preference, mail-outbox, or worker subsystem. The Phase 7 operations endpoint and UI accurately say notifications are unavailable.
- The existing React app is role-aware and uses Axios plus TanStack Query. The authenticated shell is in `frontend/src/App.tsx`; admin operations are grouped in `AdminOperations.tsx`; `api.ts` provides the shared client. Existing UI styling is plain CSS and React escapes normal text interpolation.
- The Phase 7 migration is defensive for historical and fresh schemas and deliberately keeps additive audit history on downgrade. Migration tests upgrade from a historical predecessor and check re-upgrade/non-destructive behavior. Backend API tests use isolated SQLite metadata; frontend tests use Vitest and Testing Library.

## Event boundaries reviewed

1. **Commerce/orders:** `commerce.py` creates orders in checkout (demo payment is explicitly simulated; COD is unpaid), cancels eligible orders, advances admin fulfillment status, and separately records COD collection after delivery. Cart edits and checkout retries are not user-notification events. Order notifications must reflect recorded state only and must never promise shipment, a digital payment, a refund, or money movement.
2. **Campaigns/applications:** campaign status transitions are in `campaigns.py`; creators apply there and brand/admin users review applications. These are clean event points for application received/decision and campaign published/paused/cancelled/completed notifications.
3. **Rewards:** `rewards.py` delegates approve/reject/reverse/simulate to `services/rewards_engine.py`; reward events and ledger entries are already recorded there. A simulated payout is labeled as a simulation and explicitly reports `actual_money_transferred: false`; notifications must preserve that disclosure and not imply an actual payout.
4. **Authentication/security:** `auth.py` handles email verification, password reset, login sessions, logout, logout-all, refresh reuse detection, and account action tokens. Verification/reset messages contain one-use credentials and need stricter treatment than ordinary notices; no raw token may be logged or exposed in an in-app notification/admin monitor. Existing generic account-recovery responses and session revocation behavior must remain intact.
5. **Administration:** `admin.py` includes lifecycle changes with session revocation, manual verification, campaign moderation, risk review, and disputes; admin actions are reasoned/audited. These do not all warrant end-user messages (e.g. private investigation/risk details); only carefully chosen public state changes should notify affected users.

## Constraints and decisions for implementation

- Extend current models, auth, event boundaries, SMTP abstraction, router, React shell and admin operations. No new auth, commerce, campaign or reward system.
- Use a small SQL-backed in-app notification store and email outbox; a separately run polling worker is preferable to sending email in API requests. No Redis/Celery/Kafka/RabbitMQ addition. Deployment must run the documented worker command for delivery; absent worker/provider is not reported as healthy.
- Persist notifications and outbox rows transactionally with the business action. Enforce an event idempotency key at the database layer, scope every user read/mutation to the authenticated recipient, paginate bounded results, and bound retry count/backoff. Worker claims must avoid making an untested cross-database concurrency guarantee; report SQLite/PostgreSQL limitations explicitly.
- Store only safe, bounded notification content. Never render notification text as HTML, permit arbitrary notification URLs, put reset/verification tokens in notifications or delivery-monitor responses, or interpolate user content into mail headers. Account-action emails remain generic and one-use; evaluate protected queuing before changing their existing request path.
- Keep notification category preferences explicit and preference-aware. Essential security/account emails must not become a way to enumerate accounts or evade existing generic responses. Security-relevant events should be exposed only to the account owner and should not reveal tokens, credentials, or private moderation/risk context.
- Provide an admin delivery view showing aggregate/status/timing/attempt/error-category information only; avoid recipient plaintext, secret payloads and provider credentials. Mark SMTP as configured only from configuration, not by probing/pretending a delivery succeeded.
- Existing API semantics and financial invariants take precedence over convenient event coverage. In particular, no real payment/payout/refund/shipping integrations currently exist.

## Implementation sequence

1. Add additive Phase 8 models and migration for notification preferences, recipient notifications, and retryable email deliveries; add migration upgrade/re-upgrade checks.
2. Add a notification/event service with safe templates, recipient/event deduplication, category preferences, transactional inserts, and an email-provider adapter. Add a bounded polling worker/CLI with retry/backoff, stale-claim recovery, safe failure classification, and truthful disabled-provider handling.
3. Integrate a scoped set of order, campaign/application, reward, and security/account lifecycle events at their existing transaction boundaries. Keep admin-only risk/dispute data private. Review auth action-email queuing separately to avoid storing raw one-use credentials without encryption.
4. Add authenticated notification list/unread/read/preferences APIs with recipient scoping and pagination; add admin delivery summary/list APIs requiring admin role.
5. Add a user notification center and settings page/controls to the existing role-aware shell, plus admin delivery monitoring and honest integration/worker status.
6. Add backend tests for migration, event idempotency, preferences, ownership/IDOR, pagination, retries, provider-disabled and security behavior; frontend tests for inbox/settings and admin monitor. Update architecture, Phase 8 documentation, README/project status and roadmap.
7. Run actual backend/frontend checks, inspect staged diffs before each logical commit, commit milestones to this branch only, push only this branch, and verify the remote SHA and clean worktree.

## Baseline checks

- Frontend baseline: `npm test -- --run` — **8 test files, 35 tests passed**. Existing Recharts width/height warnings were printed by campaign-intelligence tests.
- Backend baseline: initial `pytest -q` could not start because pytest was not on PATH. The repository's supported venv was then located and `backend/.venv/bin/pytest -q` passed **57 tests** with one existing Starlette/httpx deprecation warning. This verified baseline predates Phase 8 implementation.

## Open implementation risk

The existing auth mail path includes a one-use raw token only in memory and sends immediately after commit. A durable asynchronous outbox cannot safely persist that message body in plaintext. Either retain the existing action-email path as a clearly documented exception while all ordinary notifications use the queue, or implement authenticated encryption at rest with rotation/retention considerations and tests before moving action mail to the outbox. Do not quietly put raw tokens in an outbox payload.
