# Phase 7 — Platform administration audit

**Audit date:** 2026-11-25  
**Branch:** `arena/e6c9b4f7-crownd-2-0`  
**Baseline:** `d581d108f0ebc2813951447bff0b60f6a8e1a91e` (Phase 6 documentation commit); initial worktree clean.

This is a pre-implementation audit, based on the current repository source and existing Phase 1–6 documentation. It records the starting architecture and decisions for extending it; it is not a claim that the baseline already provides the Phase 7 workflows.

## 1. Existing systems to extend

- **Identity and sessions:** `User` has `role`, `is_active`, and email verification. `AuthSession` persists refresh-session state. `current_user` checks that session and current account state on every protected request, and `revoke_sessions()` revokes refresh sessions. This provides immediate access-token invalidation after a user is deactivated, but there is no administrator lifecycle endpoint or session revocation UI.
- **Authorization:** `require_role("admin")` is used on existing admin analytics, referral/risk, order, and reward APIs. The browser also has role-based path checks; this is convenience only and cannot replace backend enforcement. Existing admin controls are spread across route modules.
- **Profiles and manual review:** `BrandProfile.verification` exists with a default of `unverified`; `CreatorProfile` has no verification state. No manual-review endpoints or review provenance exists. Do not describe this as external verification.
- **Campaigns:** `Campaign`, its lifecycle and Phase 6 visibility/product configuration already exist. The legacy admin campaign transition is embedded in the regular campaign status endpoint and permits rejection without a reason; it is not a dedicated moderation queue.
- **Risk:** `ReferralRiskFlag` and `flag_risk()` are already the explainable referral/conversion review system. Existing sources include self-referral/ineligibility, repeated customer pattern, and high click volume. Existing admin APIs list/review those flags; reviewed state is mutable and currently does not require a review reason. There is no generic risk case model. Do not build a duplicate risk scorer or treat a weak signal as an automatic ban.
- **Financial history:** `LedgerEntry` and `RewardEvent` are protected as append-only in the ORM and, from migration 0006, database triggers. Admin reward operations use the established reversal mechanism. Phase 7 disputes must not edit or delete ledger/financial history and cannot imply refunds.
- **Audit:** existing business writes create `AuditLog` rows, and `/admin/audit-logs` reads up to 200. The table has no reason/metadata fields or database/ORM append-only enforcement; admin account actions, verification, moderation, and risk dispositions are not complete there.
- **Admin UI:** `App.tsx` contains role-specific navigation and routes to Phase 6 analytics, referral review, orders, rewards, and a basic administration surface. `GET /admin/users` currently returns a bounded but unfiltered list including email. There is no dedicated platform operations dashboard, lifecycle action, dispute queue, health/coverage distinction, or searchable unified audit view.

## 2. Trust boundaries and specific gaps observed

1. `current_user` correctly reloads the user and session from the database. Updating `is_active` will therefore deny future API requests using existing access tokens, but explicit session revocation remains important for refresh/session state and should be done transactionally.
2. Existing admin listing is read-only, but exposes full email to the browser and has no search/pagination contract. Admin output should minimize PII by default; searching email may be permitted but responses should mask it unless operationally required.
3. Profile verification is a manual workflow gap; no externally verified evidence is available. Verification actions require a reason and must be recorded as manual decisions.
4. Campaign status and public visibility affect attribution eligibility. Moderation must use current campaign lifecycle semantics and audit reasoned transitions, without deleting campaign/application/referral history.
5. Current risk flags can contain a visitor hash/customer FK internally; user-facing review payloads must not expose these values. Review reasons are absent. Existing signals already state that repeated customer patterns are for review only.
6. `AuditLog` rows are appended by current service code but the model has no immutable guard. A new dedicated admin event stream can carry required reason/context and append-only guarantees while keeping existing historical audit rows readable.
7. No dispute entity exists. A dispute is an operational case, not proof of fraud, financial settlement, or a customer refund. It should reference existing order/conversion/reward resources, preserve immutable case events, and leave ledger entries untouched.
8. Health endpoint reports only API process availability (`/health`); it does not verify database, email, Redis, or other external services. Dashboard must label the narrow probe accurately and show unavailable where no metric is implemented.
9. There is no configured notification delivery/persistence system. Admin notification counts cannot be fabricated; only actionable in-app queue summaries derived from real rows are appropriate.

## 3. Integration decisions and acceptance criteria

- Build an admin module using existing `User`, `AuthSession`, `BrandProfile`, `CreatorProfile`, `Campaign`, `ReferralRiskFlag`, `Order`, `Conversion`, `Reward`, and `LedgerEntry` entities and the current `require_role` dependency. All admin API authorization stays server-side; do not rely on hidden routes or role menu filtering.
- Account lifecycle supports active/suspended state with required confirmation phrase/reason, revokes every active session, preserves role and account identity, and never accepts a new role from the request. Prevent self-suspension and protect the last active admin; do not create/grant admin roles through this interface.
- Add manual verification state for creators and extend existing brand verification review; only `unverified`, `verified`, or `rejected` outcomes, with a reason and explicit “manual review” presentation. No external check, identity evidence, or verification claim is invented.
- Add a dedicated campaign moderation action with constrained current-state transitions, reason, audited outcome, and Phase 6 visibility/Phase 4 eligibility behavior preserved. No direct deletion or silent state rewrite.
- Reuse existing explainable risk flags as the centralized investigation source. Add reasoned review/disposition; list provenance and explanations without exposing hashes/customer contacts. No automated ban, account suspension, reward rejection, or financial action based solely on weak risk indicators.
- Add disputes as append-only case/event records referencing existing financial/commerce entities where applicable. Resolution records findings/reason and can close the case; it does not mutate ledger/reward/conversion/order financial history, perform refund, or claim money movement.
- Add an append-only admin audit event model/table for all new sensitive administrative writes, capturing actor, action, entity, bounded reason and safe metadata; prohibit ORM updates/deletes and install database-level guards where practical. Preserve `AuditLog` compatibility and never expose secrets or unnecessary customer PII.
- Provide bounded search and pagination, truthful queue counts and a platform operations dashboard. Service health must distinguish the simple API liveness endpoint from database/provider health; report unimplemented integrations as unavailable, not healthy.
- Integrate admin navigation/UI into the existing React application and visual system. Require explicit user confirmation and reason for dangerous actions; backend remains authoritative.
- Use additive migrations only; preserve financial/audit history; test SQLite fresh and upgrade paths plus downgrade/re-upgrade where safe. Run backend/frontend tests, lint/type/build, compile, migration checks, and security-focused tests. PostgreSQL/browser E2E and production readiness must be honestly scoped.

## 4. Planned implementation boundaries

Phase 7 adds a migration after `0007_campaign_intelligence`, a dedicated admin API module/service/schema and admin UI component(s), focused authorization/lifecycle/migration tests, and updates to status, roadmap, security and Phase 7 docs. It does not repeat Phase 6 analytics, add an external verification provider, real notification delivery, a risk-model replacement, a payment/refund provider, or actual payout settlement.
