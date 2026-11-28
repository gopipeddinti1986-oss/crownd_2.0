# Phase 14 — Feature freeze and functional gap closure

**Status:** PASSED — local feature freeze and gap-closure gate met; explicitly deferred capabilities remain out of scope.
**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Git baseline:** HEAD was `8cacf7f6aa136f51bb8731bffdf85b090f1b4f56`, matching the origin-tracking branch when checked after implementation. Pre-edit worktree cleanliness was not established; all observed edits were reviewed and preserved/staged explicitly.
**Approach:** Functional changes only; no UI redesign. PostgreSQL/browser infrastructure remains assigned to the later Phase 17 environment stage per the master directive. This does not change the previously recorded Phase 13 NO-GO or claim its infrastructure checks passed.

## Audit method and baseline

Reviewed the Phase 12/13 audits and current FastAPI routes, SQLAlchemy models/migrations, React route/navigation/API wiring, and test inventory. The working tree was clean at the baseline. Existing application test coverage includes API and role/ownership checks plus Vitest/jsdom component checks; it is not browser E2E.

Baseline at start of this Phase 14 checkpoint:

- Backend: **84 passed, 4 skipped** (four opt-in PostgreSQL tests); `compileall` passed; Alembic head `0010_integration_snapshots`.
- Frontend: **54 passed / 14 files**; lint and TypeScript/Vite build passed.
- PostgreSQL: not tested; no approved target. Chromium/browser E2E: not tested.

The functional change in this checkpoint adds a creator-owned withdrawal path for pending/shortlisted campaign applications. It retains history, blocks unauthorized withdrawals, rejects withdrawal after acceptance/rejection, audits the action, notifies the campaign brand once, and is wired to the existing Applications UI. It does not add reapplication or post-acceptance partnership withdrawal.

## Feature matrix (initial audit, updated for this checkpoint)

“COMPLETE” means the stated local product scope is connected through frontend/API/data and has tests; it does not imply browser, PostgreSQL, external-provider, or production verification.

| Feature / workflow | User role(s) | Frontend location | Backend / persisted data | Dependencies | Status | Gaps, security concerns and tests |
|---|---|---|---|---|---|---|
| Register, sign in/out, session refresh | All | `AuthFlows.tsx`, `App.tsx` | `/auth/register`, `/login`, `/logout`, `/refresh`; users, sessions | Email provider for verification | COMPLETE (local) | Auth workflows tested; actual SMTP and browser cookies remain unverified. |
| Email verification and password recovery | All | `AuthFlows.tsx` | verification/reset endpoints, one-use token tables, encrypted outbox | SMTP worker/provider | PARTIALLY COMPLETE | Local token/outbox/retry behavior tested; real provider acceptance/inbox delivery is not. |
| Profile view/edit | Customer, creator, brand, admin | `AccountProfile.tsx` | `/auth/me`, `/me/profile`, role profiles | None | PARTIALLY COMPLETE | Basic role-scoped edits and audit tests pass. Customer saved-address book and external identity verification are absent. |
| Role/ownership enforcement | All | `routes/access.ts`, `App.tsx` | `current_user`, `require_role`, ownership filters | Auth/session DB | COMPLETE (local API scope) | Cross-user, role and admin restrictions have tests; no independent penetration test or browser guard test. |
| Product discovery/detail | Customer, public | `CustomerCommerce.tsx` | `/products`, `/products/{id}`, categories/brands | Product rows; image URLs | COMPLETE (local) | Search/sort/pagination/API tests and jsdom tests pass; actual image hosting/browser not tested. |
| Search/filter/sort/pagination | Customer, creator, brand, admin | Shop, campaign/creator/admin views | Product/campaign/report query params | Existing query APIs | PARTIALLY COMPLETE | Several endpoints cap result sets or return unpaginated application lists; some role views have limited filter controls. No browser usability verification. |
| Persistent cart and quantity management | Customer | `CustomerCommerce.tsx` | `/cart`, `/cart/items`; carts/cart_items | Database concurrency | COMPLETE (SQLite/API scope) | Ownership, price and stock validation tested. Concurrent first-cart/checkout PostgreSQL properties remain blocked. |
| Checkout/address snapshot | Customer | Checkout in `CustomerCommerce.tsx` | `/checkout`; orders/order_items and shipping JSON snapshot | Supported demo or COD mode | COMPLETE (local checkout scope) | Server totals/validation, idempotency, inventory and snapshots tested. Saved-address book and shipping quote are not implemented. |
| Saved customer address book | Customer | No address management UI | No address CRUD/table | Data retention/product decision; schema migration | MISSING | Prior Phase 12 P2 gap. Current checkout collects an address per order and stores an order snapshot. Consider retention/deletion and consent before adding reusable PII storage. |
| Demo payment and COD | Customer, admin | Checkout, order details/admin order page | Payment attempts, order/payment status, collection endpoint | Admin collection action for COD | COMPLETE (simulated scope) | No real payment, cash transfer, refund, or payout is claimed. Payment and COD lifecycle tests pass. |
| Order history/detail/cancel | Customer, brand, admin | `CustomerCommerce.tsx`, admin operations | `/orders`, `/orders/{id}`, cancel/status routes | Inventory transaction | COMPLETE (local eligible scope) | Ownership, repeat cancellation/restock and payment-state tests pass. Paid refund flow is intentionally unsupported. |
| Creator profile/discovery | Creator, brand/admin discovery | `AccountProfile.tsx`, `CreatorsPage` | `/creators`, `/creators/me`, profiles | External social verification is not integrated | PARTIALLY COMPLETE | Profile values are creator-reported. No external metric verification or provider is present. |
| Campaign discovery/detail | Creator, public | Campaign discovery in `App.tsx` | `/campaigns`, detail, application APIs | Published/active campaigns | COMPLETE (local scope) | Lifecycle/date/status filters and UI states are tested; creator discovery is capped and browser E2E is absent. |
| Application submission/review | Creator, brand, admin | `ApplicationsPage` | `/campaigns/{id}/applications`, `/applications/{id}`; applications/referrals | Active campaign, account eligibility | COMPLETE (local scope) | Ownership, duplicate submission and status transitions tested. Collaboration deliverables and application list pagination are absent. |
| Creator withdraws an application | Creator, brand recipient | Applications screen | New `/applications/{id}/withdraw`; application, audit log, notification, referral | Pending/shortlisted application | COMPLETE (local tested scope) | New regression verifies ownership, replay dedupe, audit/notification and accepted-app protection. Reapplication and post-acceptance withdrawal remain undefined/deferred. |
| Creator invitations | Brand, creator | No Invite action (removed as misleading) | No invitation model/API | Product acceptance criteria and email workflow | DEFERRED | Not part of current apply-first workflow; no fake invite UI. Revisit only with invitation semantics and recipient acceptance behavior. |
| Referral links and attribution | Creator, customer, admin | Referral dashboards and `/r/{code}` | referral routes/clicks/visitor attribution/order items | Cookie persistence, DB | COMPLETE (SQLite/local) | Eligibility/expiry/tampering and mixed-cart tests pass. PostgreSQL/multi-worker and browser-cookie continuity remain unverified. |
| Conversion lifecycle and analytics | Creator, brand, admin | Analytics/referral dashboards | conversions/events and order-item attribution | Correct payment/order transitions | COMPLETE (local semantics) | Duplicate/replay, mixed-cart and scoping tests pass. External reporting reconciliation/browser remains absent. |
| Reward calculation and snapshots | Creator, brand, admin | Rewards and admin rewards | `rewards_engine`, reward rows/snapshots | Conversion, campaign terms, payment status | COMPLETE (SQLite/local scope) | Decimal/snapshot, COD gate, duplicate processing and tamper-risk tests pass. PostgreSQL race safety remains blocked. |
| Ledger and simulated payouts | Creator, admin | Earnings and admin reward surfaces | append-only ledger/event/payout records | Reward state | COMPLETE (no real transfer) | ORM/SQLite immutability and simulation disclosures tested; no actual payout/refund service. |
| Brand profile/manual verification | Brand, admin | Profile and admin operations | role profiles, verification endpoints/audit | Manual operator review | PARTIALLY COMPLETE | Manual verification exists; no external business identity provider. |
| Brand product catalog/inventory | Brand, customer, admin | Products and admin operations | `/brand/products`, product create/update/status/moderation | Brand ownership and campaign eligibility | COMPLETE (local CRUD/soft state) | Ownership, stock/status, moderation and history preservation tested. Product images are URLs; no upload/storage workflow. |
| Campaign authoring/lifecycle/rules | Brand, creator, admin | Brand Campaign Workspace, discovery | campaign create/edit/products/status and applications | Product ownership, active users/date windows | PARTIALLY COMPLETE | Core draft/publish/pause/complete/cancel and reward terms exist and are tested. No invitations/conversations/deliverables; lifecycle stays within existing statuses (no invented archive state). |
| Brand/creator/admin analytics | Brand, creator, admin | Campaign intelligence, referral/rewards | analytics API/service aggregates and exports | Persisted orders/conversions/rewards | PARTIALLY COMPLETE | Local ownership/item attribution and privacy tests exist. Spend/true ROI is unavailable; no external financial reconciliation. |
| Admin users/moderation/audit | Admin | `AdminOperations.tsx`, admin pages | `/admin/*`, audit and moderation models | Admin role, reason/confirmation | COMPLETE (local scope) | Role, audit, lifecycle and moderation tests pass. No separate penetration/operational dashboard review. |
| Disputes/reward holds | Customer, creator, brand, admin | Order issue form/admin disputes | `/disputes`, `/admin/disputes`; dispute/reward/audit | Storage required for attachments | PARTIALLY COMPLETE | Ownership-scoped intake, admin decision and ledger-preserving hold/release tested. Evidence attachments and financial remedies are absent. |
| Dispute evidence attachments | Customer/participant, admin | No attachment UI | No secure upload/storage API | Object storage, malware/content policy, ACLs | DEFERRED / BLOCKED | Do not store uploaded files locally or imply attachments exist. Requires secure storage/retention/access decisions; infrastructure belongs in Phase 17. |
| Notifications/preferences/outbox | All, admin operations | Notification center/settings/monitor | notifications/preferences/encrypted email outbox/worker | SMTP and multi-worker DB semantics | PARTIALLY COMPLETE | Persistence, role scope, dedupe, retry/failure tests pass locally. Provider delivery, PostgreSQL concurrency and production worker are unverified. |
| Support/help | All | Unavailable notice | No ticket/contact endpoint | Owner-provided destination/service | BLOCKED | Destination has not been supplied; no fake support form or dead-end button. |
| Creator social verification | Creator, admin | Self-reported fields/disclosure | Profile fields only | External provider/manual evidence policy | DEFERRED | No verified badge or third-party metric claim should be made. |
| Disputes, refunds, real payment/payout | All | Only supported UI labels and simulation disclosure | Demo/COD and simulated payout only | Real financial providers (out of scope) | DEFERRED | No real-money functionality is to be added in this phase. |
| Loading/empty/error/retry states | All | Role pages and commerce flows | API response/error contracts | Network/API availability | PARTIALLY COMPLETE | Component tests cover major pages; complete route-by-route browser verification is blocked. |
| Database schema/migrations | System | Not user-facing | Alembic 0001–0010 | PostgreSQL runtime | PARTIALLY COMPLETE | Fresh/historical SQLite paths pass. PostgreSQL migration/constraints/triggers are blocked to Phase 17; do not infer compatibility from SQLite. |

## Functional gap closure in this checkpoint

### Creator application withdrawal

- Added creator-only `POST /api/v1/applications/{application_id}/withdraw`.
- The endpoint locks the application where supported, returns 404 for a non-owner, permits only `pending`/`shortlisted`, and returns a stable no-op response on replay of an already-withdrawn application.
- Accepted/rejected applications cannot be withdrawn through this pre-acceptance action. Existing application history remains; a withdrawal does not delete the application.
- On first withdrawal, the server deactivates any associated referral, writes an audit event, and creates a deterministic brand notification. A repeated request does not create duplicate audit/notification records.
- `ApplicationsPage` now exposes a role-appropriate withdraw button only for pending/shortlisted creator applications, disables it during the request, reports failures, and refreshes status from the API.
- Tests: backend `test_creator_can_withdraw_pending_application_once_and_cannot_withdraw_accepted`; frontend application component suite covers creator visibility, request/refresh, and no brand-only actions.

## Scope decisions and remaining work

- **In scope and implemented here:** creator withdrawal before acceptance, because it closes a small existing application lifecycle gap without schema/storage redesign.
- **Saved addresses:** still missing. Treat as a Phase 14 candidate; before storing repeat addresses, define deletion/default/retention behavior and add ownership-scoped storage plus UI/tests. Order address snapshots remain available.
- **Invitations/messaging:** deferred until product defines invite acceptance, collaboration, message retention and notification semantics. Current apply-first workflow remains honest.
- **Evidence uploads:** deferred to Phase 17 because safe upload requires storage isolation, limits, content validation, private access, retention and cleanup; no local file-upload stand-in was introduced.
- **Support:** blocked on an owner-provided destination.
- **Social metric verification / real payment, refunds, payouts:** deferred/external or intentionally out of scope.
- **Phase 15/16/17:** not started. No comprehensive QA phase or visual redesign was performed; only regression checks for the Phase 14 feature were added. PostgreSQL/browser environment work remains for Phase 17 and no Neon/Supabase/production connection was made.

## Verification for this checkpoint

- Targeted backend withdrawal regression: **1 passed**.
- Targeted frontend `App.applications.test.tsx`: **4 passed**.
- Full backend: **85 passed, 4 skipped**, one upstream Starlette/httpx warning; skips are PostgreSQL-only.
- Full frontend: **55 passed across 14 files**, with existing Recharts jsdom zero-size warnings.
- `npm run lint`: passed.
- `npm run build`: passed, including TypeScript `tsc -b`.
- Backend `compileall`: passed; Alembic head remains `0010_integration_snapshots`.
- No browser E2E, PostgreSQL, SMTP, deployment or production check was run.

## Phase 14 gate

**PASSED (local feature-freeze scope).** The inventory has been audited against the actual code and test evidence; the in-scope creator application-withdrawal gap is implemented end to end and regression-tested; unsupported/incomplete features are explicitly recorded as deferred, blocked on owner/product decisions, or external runtime validation rather than being represented as working. No Phase 14 item requires an unsafe data migration or external integration to be claimed complete. Deferred P2/P3 work (saved addresses, application pagination/reapplication policy, collaboration and evidence storage, support destination) is deliberately not smuggled into the frozen scope. Real payment/refund/payout remains excluded. This gate is **not** a PostgreSQL, browser, SMTP, deployment, or Phase 13 infrastructure PASS; those remain Phase 17 work. Phase 15 may begin; Phase 16 remains gated on Phase 15.
