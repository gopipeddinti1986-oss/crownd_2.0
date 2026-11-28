# Phase 12 — Implementation log

**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Starting revision:** `3f8ae348d16ed885bb4c9c1e163c63ed4da711d1` (branch base: `67e80eb50c04fcfb3d4e654e12e50dd0cc8ff516`)
**Scope rule:** incremental repairs to the existing product. No redesign, schema replacement, real payment gateway, payout transfer, or external integration was added.

## Audit and baseline

- Created [`PHASE_12_FEATURE_AUDIT.md`](PHASE_12_FEATURE_AUDIT.md) after reviewing route/API handlers, service logic, model constraints, migrations, frontend route/navigation/pages/components, tests, and Phases 5–11 records.
- Baseline before code changes: backend **74 passed**; frontend **38 passed**, lint passed, and TypeScript/Vite build passed. Baseline results were local test/build evidence only.
- No migration was required; current Alembic head remains `0009_notifications`.

## Implemented fixes

### 12.1 Strict creator-profile request validation

- Added `backend/app/schemas/workflows.py` with a strict `CreatorProfileUpdate`: extra keys rejected; fields bounded; username character/length rules; followers and engagement constrained; empty and explicit-null updates rejected.
- `/creators/me` now returns 404 when the user has no profile, enforces username uniqueness before writing, prevents unvalidated assignment to profile fields, and returns the updated profile payload.
- Added coverage for successful edits, malformed/extra/null/empty requests, negative and out-of-range metrics, username format/collision, wrong-role denial, and missing profile.

### 12.2 Application payload and review lifecycle

- Application submit/review routes now use strict Pydantic models; creator messages are bounded to 2,000 characters and unknown keys fail validation.
- Reviews lock the application row where supported. Repeating the existing status is a no-op (no extra referral, audit event, or notification); permitted transitions are pending → shortlisted/accepted/rejected and shortlisted → accepted/rejected. Invalid terminal transitions return 409.
- Regression coverage includes invalid/oversized payloads, duplicate applications, missing application, creator/other-brand access denial, unknown fields/statuses, repeated review and no repeated side effects.

### 12.3 Dashboard and navigation truthfulness

- Removed built-in sample campaign fallback data from dashboard and discovery views; they now render loading/error/retry/real-empty states rather than presenting examples as account opportunities.
- Replaced fixed date with the current local formatted date; removed the non-functional date-range button; headline amount and orders now derive from the seven-month paid-order series and distinguish unavailable/loading states.
- Connected “Recent activity” to the actual notification inbox data and server-provided internal action paths. “See notifications” navigates; activity and analytics errors expose distinct retry actions.
- Removed the disconnected Messages navigation/placeholder and the fake “Invite to campaign” toast/button rather than implying invitations exist. Creator discovery now uses the saved bio and marks follower/engagement numbers as creator-reported; unexplained trust/crown scores are hidden from discovery pending provenance validation. Support is presented as unavailable without an action. Application access is now restricted to creator/brand/admin roles in the frontend path guard (server authorization remains authoritative).
- Marked the marketing hero’s sample campaign/partner examples as illustrative and removed invented monetary values and creator name from that example card.
- Added dashboard tests for empty, loading, error, retry, real activity and its action path; added customer role-boundary coverage for `/applications`.

### 12.4 Owner-scoped brand catalog

- Added paginated `GET /brand/products`, restricted to brand accounts and filtered by the authenticated brand ID. It returns only that brand’s product rows and preserves existing product data/API behavior.
- The brand product workspace now reads this endpoint; admins continue to use the public active catalog. The create form takes explicit numeric stock instead of silently initializing every product at 20, validates required values, reports API errors safely and invalidates the cached list after successful creation. Loading, error/retry and empty states are explicit.
- Regression test checks brand isolation, pagination, role denial and invalid page bounds. At this milestone only create/list existed; the lifecycle was extended in 12.5 with product update, stock editing and soft activation/deactivation (no hard delete).

### 12.5 Role-aware profile editing and brand product lifecycle

- Added strict role-aware `PUT /me/profile`: creators can update public profile fields, brands can update their profile, customers/admins can update display name; fields outside each role are rejected. Updates write an audit event and return updated identity/profile data. Brand websites must use HTTPS and cannot embed credentials. No email or password field can be changed through this endpoint.
- Added `/profile` UI for each role with loading/error/retry states and persistent save behavior; the authenticated user display updates after a successful name save. No customer address book was added.
- Added paginated owner-scoped brand product list (prior step) plus strict partial updates for catalog/inventory fields, sale-price integrity checks, and active/inactive status. Status changes preserve the product row and its order/referral history. Deactivation is blocked while any linked campaign is published; no hard-delete operation exists.
- Added reasoned, typed-confirmation admin product list/moderation, with append-only admin audit records.
- Files: `backend/app/schemas/workflows.py`, `backend/app/schemas/commerce.py`, `backend/app/api/v1/routes.py`, `backend/app/api/v1/commerce.py`, `backend/app/api/v1/admin.py`, commerce/admin/workflow tests, `frontend/src/components/AccountProfile.tsx`, `frontend/src/App.tsx`, product UI and admin operations components/tests. No migration required.

### 12.6 Creator discovery and application access corrections

- Creator search now includes the advertised platform field and constrains search/filter/offset inputs; the UI distinguishes loading/error/retry from a real empty result.
- Creator application rows now show status without presenting unauthorized brand review actions; only brand/admin roles see accept/reject. Application list loading, error and retry states are explicit; successful reviews refetch data.
- Fixed the topbar search affordance label to match its campaign-discovery destination; “See how it works” scrolls to the real section instead of navigating to a route that rendered the landing page again.

### 12.7 User-originated order dispute workflow

- Added role-gated `POST/GET /disputes` for customer, creator, and brand accounts. Order public IDs are resolved server-side; customers require matching owner/email, brands must own at least one line item, and creators must be the attributed creator. Non-owners receive 404 to avoid order existence disclosure. A user cannot create another open case for the same order; submissions are rate limited.
- Intake records an append-only dispute event and admin audit event, notifies active administrators through the existing in-app notification system, and does not mutate orders, payments, conversions, rewards or ledger entries. Admin status updates now notify the reporter.
- Order detail UI exposes an issue form only for roles allowed to view order details, validates summary/reason length and refreshes the reporter’s dispute list after submission. Admin retains case review/resolution UI.
- Files: `backend/app/api/v1/admin.py`, `backend/app/services/notifications.py`, `backend/tests/test_admin.py`, `frontend/src/components/CustomerCommerce.tsx`, `CustomerCommerce.test.tsx`, admin UI/tests and CSS. No migration required because `AdminDispute.opened_by` and existing audit/event tables already support the case. Evidence attachment and refund integration remain absent.

## Continuation verification (current tree)

- Backend full suite: `backend/.venv/bin/pytest -q` — **81 passed**, 1 upstream Starlette/httpx deprecation warning. `compileall -q app migrations/versions tests` passed.
- Frontend full suite: `npm test -- --run` — **54 passed** across 14 files. Existing two Recharts jsdom zero-size warnings remain.
- Frontend lint and production build (`npm run lint`, `npm run build`, including TypeScript) passed.
- Dependency audits: `npm audit` — **0 vulnerabilities**; `backend/.venv/bin/pip-audit -r requirements.txt` — **no known vulnerabilities**.
- `git diff --check` passed. No migration; Alembic head remains `0009_notifications`.
- No commit or push was performed. PostgreSQL, Docker, backup/restore, live SMTP, browser E2E, deployment and production smoke checks remain not run.

## Verification after these changes

- Backend historical Phase 12 snapshot: **77 passed** before continuation (current 81-pass result is recorded above); 1 existing Starlette/httpx deprecation warning.
- Frontend historical Phase 12 snapshot: **43 passed** across 10 files before continuation (current 54 across 14 is recorded above). Two Recharts zero-size warnings remain in jsdom chart tests; they do not fail the suite.
- Frontend lint: `npm run lint` — passed.
- Frontend production build: `npm run build` (includes `tsc -b`) — passed.
- Browser E2E, real SMTP/inbox receipt, PostgreSQL migration/concurrency, Docker/Compose, backup/restore, deployment, and production smoke checks were not run. See Phase 11 validation records; Phase 11 remains incomplete.

## Remaining work, by priority

- **P0:** Phase 11 isolated PostgreSQL and Docker/browser-capable verification (user decisions remain: do not use the connected Supabase project; Docker installation was deferred; no alternate DB endpoint supplied).
- **P1:** PostgreSQL race tests for checkout/application/admin row locks, broader malformed-input and cross-role endpoint review, independent security/accessibility verification, and validation of creator trust-score/metric provenance.
- **P2:** Product management beyond current CRUD/soft-status controls, creator invitation flow, dispute evidence attachments, and conversation messaging. These require product acceptance criteria and are intentionally not represented as implemented.
- **P3:** Real support destination and dashboard date-range control once backend range semantics are agreed.

Payment behavior remains the existing backend-simulated demo and COD only. No money transfer is enabled or claimed.
