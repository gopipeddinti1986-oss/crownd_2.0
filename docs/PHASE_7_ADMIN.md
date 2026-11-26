# Phase 7 — Platform administration and trust operations

**Updated:** 2026-11-25  
**Branch:** `arena/e6c9b4f7-crownd-2-0`  
**Audit baseline:** [`PHASE_7_ADMIN_AUDIT.md`](PHASE_7_ADMIN_AUDIT.md)

This milestone extends the existing CROWND identity, session, campaign, referral-risk, order/reward/ledger, and audit systems. It does not add an external verification provider, payment/refund service, payout rail, notification service, or a second risk engine. It is not a production-readiness claim.

## Delivered workflows

### Operations overview, search, and health honesty

- `GET /api/v1/admin/operations` derives active account, open risk, dispute, verification, and draft-campaign queue counts from stored rows. It checks a database `SELECT 1` probe.
- The dashboard distinguishes process liveness from the database probe. Email delivery and shared rate-limit storage are marked `not_probed`; online payments and payout transfers are `not_integrated`; notifications are `unavailable` because no persisted notification delivery service exists. These statuses must not be read as external-service health.
- `GET /api/v1/admin/users` supports bounded name/email search, role/state filters and pagination. It returns masked email, not full account email, and exposes no password, token, or secret.

### Account restrictions and sessions

- `POST /api/v1/admin/users/{user_id}/lifecycle` activates or suspends an existing account. It requires a reason of at least ten characters and the typed phrase `SUSPEND` or `REACTIVATE`.
- The request has no role field; request extras are rejected, so this workflow cannot create or elevate an admin. Self-suspension and suspension of the last active admin are denied.
- Suspension updates the existing `User.is_active` field and revokes all active `AuthSession` rows in the same transaction. The existing `current_user` dependency also checks current DB account/session state, invalidating already issued access JWTs on their next request.
- No account or session is deleted; role and historical rows remain intact.

### Manual verification and campaign moderation

- `POST /api/v1/admin/verification/{creator|brand}/{user_id}` applies one of `verified`, `rejected`, or `unverified` to the existing profile. Creator profiles receive a verification state through additive migration `0008_platform_admin`; brand profiles reuse `BrandProfile.verification`.
- Every verification action is recorded as `manual_review`, with a reason and typed outcome. This workflow is internal manual review only: it does not authenticate identity, fetch external evidence, or claim third-party verification.
- `GET /api/v1/admin/campaigns` provides a bounded moderation/search queue. `POST /api/v1/admin/campaigns/{campaign_id}/moderation` allows draft→published/rejected, published→paused/rejected, and paused→published/rejected. It requires reason and typed status confirmation, preserves Phase 6 visibility and Phase 4 eligibility checks, and leaves campaign history intact.
- The shared brand campaign status endpoint rejects admin moderation writes; admins must use the reasoned route instead. Brand-owned lifecycle actions remain unchanged.

### Explainable risk investigation

- The existing `ReferralRiskFlag` and `flag_risk()` remain the source of referral/conversion indicators; there is no new scoring model. The operations dashboard includes a review view backed by `GET /api/v1/admin/referral-risk` and the existing `PATCH /api/v1/admin/referral-risk/{flag_id}`.
- Risk disposition requires a human reason and is written to the append-only admin event stream. The view explains that flags do not auto-suspend accounts, reject rewards, or reverse funds. It omits visitor hashes and customer contact information.
- Existing indicators such as repeated attributed purchases are review signals, not proof of abuse. A `reviewed` or `dismissed` risk state does not itself resolve any conversion, reward, order, or ledger state.

### Disputes without financial history rewrites

- `POST /api/v1/admin/disputes` opens a case referencing at least one existing internal order, conversion, or reward ID, with summary and reason. The current UI exposes an order-ID path; the API accepts any supported reference.
- `GET /api/v1/admin/disputes` is paginated and returns case event history. `POST /api/v1/admin/disputes/{id}/status` moves open→under_review/resolved or under_review→resolved with reason and typed confirmation; resolved cases are terminal.
- `AdminDisputeEvent` records each case change append-only. Disputes are investigation records only: opening/resolving does not change an order, conversion, reward, ledger entry, or payout; no refund or financial adjustment is performed.

### Append-only administration history

- Migration `0008_platform_admin` adds `AdminAuditEvent`, `AdminDispute`, `AdminDisputeEvent`, and creator profile verification. New sensitive administrative writes record actor, action, entity, bounded reason, safe structured metadata and timestamp.
- `/api/v1/admin/audit-events` provides bounded filtering/pagination. Existing `/api/v1/admin/audit-logs` remains available for compatibility.
- ORM listeners reject update/delete for legacy `AuditLog`, `AdminAuditEvent`, and `AdminDisputeEvent`; SQLite/PostgreSQL triggers enforce database-level update/delete rejection for all three log/event tables. Current dispute state is mutable only through the API state transition; each change retains an immutable event.
- The migration is additive, supports the existing schema and the fresh metadata-driven baseline, and intentionally leaves these structures/data in place on downgrade to avoid erasing records.

## Authorization and privacy

All Phase 7 operations are protected by `require_role("admin")`; the backend validates actor/resource state regardless of frontend navigation. UI role checks are supplementary only. User search responses mask email; new audit metadata contains status transitions and internal resource IDs only. Risk endpoints do not return customer identifiers or visitor hashes. No password hashes, access/refresh tokens, or secrets are returned.

## Verification performed

- Backend full suite: **57 passed**, one existing Starlette/httpx `TestClient` deprecation warning.
- Backend `compileall`: passed.
- Frontend full Vitest suite: **35 passed**; `npx tsc -b`, ESLint, and Vite production build passed. Vite warns that the primary bundle is about 850 kB and exceeds its 500 kB advisory threshold. Existing Recharts jsdom tests emit zero-size chart warnings.
- SQLite migration tests: fresh head, historical-schema upgrade with Phase 7 fields/tables absent, downgrade-to-0007/re-upgrade, append-only trigger presence and attempted direct SQL update rejection passed.
- Role denial, masked search, session revocation, manual review audit, campaign moderation path, risk reasons, dispute/ledger non-mutation and ORM append-only checks passed in automated tests.

## Limitations and follow-ups

- PostgreSQL migration execution, production database upgrade/rollback, concurrent admin writes, browser E2E, accessibility audit, independent security review, and production observability were not run.
- Admin account bootstrap is intentionally not added; a trusted existing admin must be provisioned through the existing deployment process.
- No per-session inventory UI, account history page, notification persistence/delivery, email/Redis integration health probe, online payment, payout settlement, refund processing, dispute evidence attachments, collaboration review, or external identity verification is implemented.
- `Health` reporting here is a live database query plus declared capability limitations; it is not uptime monitoring. Local SQLite/test execution does not establish PostgreSQL or production health.
