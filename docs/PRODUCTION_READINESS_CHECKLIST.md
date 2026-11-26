# CROWND 2.0 — Production readiness checklist

**Assessment date:** 2026-11-25 (UTC)
**Branch evidence:** `arena/e6c9b4f7-crownd-2-0`, Phase 10 commit `1cda7d3` plus Phase 11 local validation work. No deployment or production service was created.
**Status meanings:** VERIFIED = executed evidence for this exact scope; PARTIALLY VERIFIED = code/test evidence exists but deployment/coverage is incomplete; NOT VERIFIED = no adequate execution evidence; BLOCKED = release gate that must be cleared before the stated readiness level; NOT APPLICABLE = explicitly outside the existing product scope (not a hidden pass).

## Phase 11 execution delta

- Docker, Compose, Podman, nerdctl and daemon sockets are absent on Debian 12. No Docker installation was performed; no apt sources are configured and OS repository access is not available in this environment.
- The connected Supabase integration reports one healthy PostgreSQL 17 project with existing CROWND-labelled migrations but no listed DB branch. The user declined its use and chose a different isolated DB; that target has not yet been supplied. Only provider metadata was read, with no SQL or data access/write.
- A new disposable SQLite DB was migrated from empty through `0009_notifications`, seeded, and used by a host-run FastAPI/Vite HTTP smoke test. Worker one-shot suppression, heartbeat, graceful SIGTERM and process restart were exercised against this SQLite DB only.
- A Playwright/Chromium package feasibility probe was installed without modifying package manifests; Chromium launch failed because the OS library `libnspr4.so` is absent. No browser E2E ran.
- Full evidence and exact commands are in [`PHASE_11_INFRASTRUCTURE_VALIDATION.md`](PHASE_11_INFRASTRUCTURE_VALIDATION.md) and [`PHASE_11_VALIDATION_RESULTS.md`](PHASE_11_VALIDATION_RESULTS.md); architecture/cost tradeoffs are in [`PHASE_11_HOSTING_EVALUATION.md`](PHASE_11_HOSTING_EVALUATION.md).

## Readiness matrix

| Area | Status | Evidence / remaining action |
|---|---|---|
| Existing app local foundation | VERIFIED | Backend full suite: 74 passed; frontend: 38 passed across 9 files; ESLint, TypeScript/Vite production build, Python compileall, backup-script `bash -n` and `git diff --check` passed in this workspace. Tests are local/SQLite and do not validate PostgreSQL or deployment behavior. |
| Production environment validation | VERIFIED | Settings reject weak/default JWT, wildcard/non-HTTPS CORS, local host allowlist, SQLite, PostgreSQL without `sslmode=verify-full`, non-TLS Redis, disabled limits/email, insecure cookies and invalid proxies. Unit tests cover representative positive/negative cases. |
| Secrets and Git hygiene | PARTIALLY VERIFIED | Root and backend templates use placeholders; `.env` ignored; tracked source scan found no common key patterns. No exhaustive historical-secret scan or external secret-manager setup. Operator must rotate any previously exposed credential. |
| Authentication/session controls | PARTIALLY VERIFIED | Prior auth/session tests cover rotation, logout, reuse revocation and suspended users. HTTPS/browser cookie behavior, provider origin and production proxy are untested. No MFA or independent auth review. |
| Authorization/privacy/ownership | PARTIALLY VERIFIED | Existing Phase 9/full backend role tests pass. This is not an exhaustive endpoint access-control/PII review or external audit. |
| Security headers/CORS/host checks | PARTIALLY VERIFIED | TestClient verifies request ID, `nosniff`, frame denial, Permissions-Policy and bad-host rejection; Nginx config sets CSP/cache headers. No running Nginx/reverse proxy/TLS browser validation. HSTS must be configured at HTTPS ingress. |
| Rate limiting | PARTIALLY VERIFIED | Shared-storage requirement enforced at production config and route decorators cover auth, key commerce/referral/admin/notification routes; an admin mutation test returns 429. No deployed Redis, multi-instance, failover or full endpoint coverage test. |
| Logging/error redaction | PARTIALLY VERIFIED | API uses generic unexpected errors, query-free request logs/request IDs; tests assert a synthetic query token is not logged and health errors do not expose DB detail. Nginx/production platform log pipeline not run. |
| Liveness/readiness | PARTIALLY VERIFIED | `/health/live` is process-only; `/health/ready` probes DB with generic failure response. TestClient validates success/failure. No actual container/host healthcheck run; readiness does not probe Redis, SMTP, migrations or worker. |
| PostgreSQL ORM/runtime | BLOCKED | Supabase provider metadata reports a healthy PostgreSQL 17 service, but no app connection was attempted. Local `psql`/PostgreSQL tools and Docker are absent; no constraints, pool, decimal/transaction/trigger/row-lock or app runtime check occurred. Existing project is not confirmed isolated. |
| Alembic migration graph | PARTIALLY VERIFIED | Repository has one head `0009_notifications`; Phase 11 fresh SQLite upgrade from `0001` to `0009` passed and Phase 9 copied-SQLite historical upgrade passed. PostgreSQL fresh/existing upgrade/downgrade/re-upgrade and representative data preservation remain blocked. |
| Migration execution strategy | VERIFIED (design) | API image no longer runs migrations at startup; Compose has one-shot `migrate` job. Production operator must run one migration job before traffic and verify revision. Compose/Docker were not executed. |
| Docker images | PARTIALLY VERIFIED (source only) | Backend image uses locked runtime dependencies/non-root and frontend uses unprivileged Nginx; contexts exclude tests/env/DB. Build, user permissions, signal behavior, image vulnerabilities, final OCI digests were not validated. |
| Docker Compose | PARTIALLY VERIFIED (syntax only) | Compose YAML parsed with PyYAML; DB/API/web/worker/mailpit service graph and no direct DB/API host port are visible. `docker compose config`, build/up, health/network/port behavior were not run because Docker/Compose are absent. |
| Frontend production deployment | PARTIALLY VERIFIED | Vite build/`tsc -b`, 38 component tests and ESLint pass; same-origin API path and SPA fallback are configured. No deployed static host, Nginx execution, browser E2E, accessibility or cross-site cookie validation. |
| Frontend performance | VERIFIED (bundle artifact only) | Entry JS reduced from Phase 9's 864.17 kB to 361.93 kB (111.12 kB gzip) using lazy-loaded feature/chart chunks. Recharts remains a 381.09 kB on-demand chunk; no browser performance/Lighthouse test. |
| Worker bounded retry/error classes | PARTIALLY VERIFIED | Existing unit tests verify SMTP classification/backoff; Phase 11 ran one-shot worker against isolated SQLite and confirmed disabled-provider suppression (`provider_disabled`, attempt 1). Live SMTP and PostgreSQL claim/retry behavior remain unverified. |
| Worker liveness/monitoring | PARTIALLY VERIFIED (local process only) | Host-run worker heartbeat appeared after a DB poll, disappeared on SIGTERM, and a second process restarted. Compose healthcheck, PostgreSQL outage/recovery, hosted restart/alert policy and outbox backlog monitoring remain untested. Admin API intentionally still says `not_measured`. |
| Email/SMTP | PARTIALLY VERIFIED | SMTP abstraction has timeout/TLS behavior and mock classification/redaction tests. No real relay credentials, provider acceptance, inbox delivery, bounce/complaint handling or DNS reputation test. |
| Database backup creation | NOT VERIFIED | Age-encrypted, permission-restricted `pg_dump` script and policy documented; PostgreSQL/pg_dump/age absent so no backup artifact was created. |
| Database restore/recovery | BLOCKED | Restore helper only creates a new local test DB; no client tools/server available, so no restore rehearsal, data-integrity result, RPO/RTO or recovery timing. Provider backup features are not configured. |
| Dependency security | VERIFIED (point-in-time scan) | `npm audit --audit-level=high`: 0 findings. `pip-audit -r backend/requirements-runtime.lock`: no known vulnerabilities after replacing `python-jose` with PyJWT; lock hash install dry-run passed. Future advisories/base images still require monitoring. |
| Python runtime lock | VERIFIED (resolution/install validation) | `requirements-runtime.lock` pinned/hashes resolved from Python 3.11; `pip install --dry-run --require-hashes` succeeded in this environment. No clean Python 3.11/3.12 container build. |
| Browser critical journeys | BLOCKED | No browser E2E ran. A Playwright/Chromium feasibility probe failed to launch because `libnspr4.so` is missing; component tests and HTTP smoke checks are not E2E. Customer/creator/brand/admin, refresh-cookie, checkout and cross-role journeys remain unexecuted. |
| Accessibility | NOT VERIFIED | No axe/browser/screen-reader/keyboard audit performed. |
| Observability/error monitoring | BLOCKED for production | Safe local logs and health paths exist; no deployed metrics/alerts/error tracker/database dashboards/incident routing configured. |
| HTTPS/TLS/edge | BLOCKED | No TLS provider, domain, certificate, reverse proxy or HSTS deployment executed. Production must verify certificate, forwarding trust, HSTS and origin behavior. |
| Incident response/on-call | NOT VERIFIED | No named owner, on-call, escalation, incident playbook or tabletop exercise exists in this Phase 10 work. |
| Data privacy/legal | BLOCKED | No formal privacy/retention/deletion/consent, jurisdictional legal or financial/commercial review. Referral/analytics and customer data use must be reviewed before real users. |
| Real payment/refund/payout | NOT APPLICABLE to current implementation; BLOCKED for real-money launch | Current demo/COD only; online payment, gateway, refunds, chargebacks and payouts are not integrated. No real-money claims permitted. |
| Provider/cost approval | NOT VERIFIED | Supabase metadata was inspected read-only but its existing project is not confirmed isolated and was not selected. No provider plan/pricing, region, account, cost ceiling or deployment was approved. Compare current quotas/free-tier terms, data residency, backup and cost before authorization. |

## Release gates

Do not label the system production-ready until all BLOCKED items required for the launch scope have execution evidence, at minimum:

1. PostgreSQL fresh install and existing-data upgrade against the target major, migration rollback/recovery approach, transaction/trigger/outbox behavior and concurrency checks.
2. Docker/Compose or target platform end-to-end deployment, one-shot migration job, readiness, worker supervision, proxy/host trust and graceful restart.
3. Verified encrypted backup and successful isolated restore, retention/off-site protection, owner-approved RPO/RTO and incident recovery exercise.
4. TLS/CORS/cookie/CSRF-origin flows through actual HTTPS frontend/API domains, browser login/refresh/logout and checkout journeys.
5. Real SMTP test mailbox acceptance and inbox/bounce/error/retry operation; monitored worker and failed-outbox alert.
6. Platform logs/metrics/alerts, capacity/connection/pool limits, load/concurrency and accessibility/E2E checks.
7. Independent security review/penetration test, privacy/legal/data-retention review, incident owner, rollback rehearsal, provider/cost and release sign-off.

## Verdict

- **Local code/test foundation:** **VERIFIED** by the listed backend/frontend checks. Phase 11 SQLite host-process API/frontend/worker smoke checks passed. **Local Compose operation:** **NOT VERIFIED** because Docker/Compose could not be run.
- **Infrastructure validated:** **NO**. A provider health metadata check is not an application PostgreSQL connection, and no container build/runtime was available.
- **Staging ready:** **NO / BLOCKED** pending an approved isolated PostgreSQL + container + TLS staging deployment and restore/worker/browser validation.
- **Production candidate:** **NOT YET**; architecture and hardening changes are a candidate foundation, not a release candidate.
- **Production ready:** **NO**. PostgreSQL, production deployment, backups/restore, real SMTP, hosted worker monitoring, browser E2E, independent security, legal/privacy and incident response remain unverified.
