# Phase 17 — Infrastructure and deployment readiness

**Status:** BLOCKED — source review and static Compose YAML checks passed, but the required isolated PostgreSQL/browser/container target is not available or verified.
**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Phase 13:** Retains its historical **NO-GO**.
**Safety boundary:** No Supabase project, production database/credential, real customer data, Neon endpoint, Vercel deployment, SMTP provider, or remote host was contacted. No destructive DB operation was attempted.

## Environment preflight

| Check | Result | Classification |
|---|---|---|
| Docker / Docker Compose executable | `docker` not found (`docker compose config --quiet` exited 127) | **BLOCKED** |
| YAML syntax / source assertions | PyYAML parser accepted `docker-compose.yml`; expected six services, DB healthcheck, and API/worker dependency on successful migrations were asserted | **PASSED (static only)** |
| PostgreSQL binaries/service | `psql`, `pg_isready`, and server utilities absent | **BLOCKED** |
| Browser binaries | Chromium/Chrome/Playwright CLI absent in this environment | **BLOCKED** |
| Isolated target environment | Environment variable names checked; no `DATABASE_URL`, `POSTGRES_*`, `NEON_*` or `SUPABASE_*` variables present | **BLOCKED — no target credentials/config supplied** |
| Source browser tests | Existing suites are Vitest/jsdom; no configured real-browser E2E runner | **NOT TESTED in browser** |
| Current backend migration head | `0010_integration_snapshots` | **PASSED (metadata only)** |
| Production deploy / cloud provider | No provider config or deployment command executed | **NOT TESTED** |

The prior Phase 11 report also documents a browser-launch failure caused by the missing `libnspr4.so`, and that no approved isolated PostgreSQL target was supplied. Phase 17 does not repeat the failed browser installation attempt or attempt to install a database/OS packages in this sandbox.

## Static infrastructure review

### API and configuration

Source review found separate liveness (`/api/v1/health/live`) and DB-readiness (`/api/v1/health/ready`) endpoints; readiness executes a trivial DB query and logs only exception type. The production settings validator requires explicit HTTPS CORS/frontend origins, non-wildcard trusted hosts, explicit trusted proxy addresses, secure cookies, TLS Redis for distributed rate limits, SMTP/STARTTLS, PostgreSQL, and `sslmode=verify-full`. Runtime DB pools enable pre-ping and bounded pool/connect settings. The API image runs as UID/GID 10001 and has a hash-locked runtime requirements file.

**Evidence limit:** These settings were not instantiated with a verified production-like environment, nor exercised against PostgreSQL, Redis, SMTP, TLS termination or an actual reverse proxy. They establish source-level guards only.

### Compose topology

The Compose YAML defines six services: `db`, one-shot `migrate`, `api`, `notification-worker`, `web`, and optional dev-profile `mailpit`. API and worker wait for healthy DB and successful migration; the database, API, worker, and web have health checks. The frontend is served by unprivileged Nginx and proxies `/api/v1/` internally; its CSP and related headers are present. The DB has a named persistent volume; local web binding defaults to loopback and local security defaults are explicitly development-oriented.

**Not verified:** Docker Compose interpolation/config validation, container builds, image pullability, healthcheck execution, start order under failure, migrations, worker heartbeat/restart, volume persistence, TLS, reverse-proxy header trust, request routing, logs, resource limits or backup/restore. Static YAML parsing is not Docker Compose validation.

## Deployment gate checklist

| Requirement | Status | Required evidence before a PASS |
|---|---|---|
| Verify database host, database name, provider project identity, disposable status, no customer data, and isolation boundary | **BLOCKED** | User/operator supplies target through approved secret-management path; verify identity and disposable designation out-of-band before connecting. Do not paste a DSN into chat or Git. |
| PostgreSQL fresh upgrade, historical upgrade, schema/index/FK/trigger checks | **BLOCKED / NOT TESTED** | Run migrations and assertions against only that verified disposable database. |
| PostgreSQL transaction/locking/concurrency workflows | **BLOCKED / NOT TESTED** | Run the four opt-in tests and additional order/cart/referral/reward/dispute/outbox scenarios on isolated Postgres. Record real outcomes, no SQLite substitutions. |
| Real browser E2E and accessibility/responsive validation | **BLOCKED / NOT TESTED** | Browser-capable runner with OS dependencies; execute customer, creator, brand, admin, checkout/COD/demo, referral and admin-authorization journeys. Add keyboard/mobile/contrast checks. |
| Docker Compose parse/build/start/restart/volume checks | **BLOCKED / NOT TESTED** | Approved Docker-capable environment; run `docker compose config`, build and non-destructive start/health/restart checks. Inspect volume targets and never run a volume-pruning command against existing data. |
| SMTP acceptance and inbox verification | **NOT TESTED** | Approved synthetic test mailbox and secret-managed SMTP credentials; report enqueue, provider acceptance, provider delivery, inbox receipt separately. |
| Backup, encryption, restore, recovery objective | **NOT TESTED** | Approved backup tool and isolated second disposable database; create encrypted backup, verify, restore and compare schema/counts/FKs/representative synthetic records; record timings. |
| Production edge TLS/HSTS, DNS, CORS, cookie, proxy, rate-limit and secret configuration | **NOT TESTED** | Staged provider deployment with explicit approved domains, TLS edge, Redis, SMTP, TLS PostgreSQL and environment review. No production deployment authorization is implied. |
| Image/dependency scanning and provenance | **PARTIAL** | npm/pip advisory audits passed at Phase 15; image scan/provenance absent because no images built. Docker base image tags are mutable tags; pin/record digests as part of actual image build/release process. |
| Operations ownership, cost ceiling, alerting/on-call, restore runbook | **NOT TESTED** | Owner-approved hosting, region/data-residency, resource/cost limits, retention, alert routing and operational runbooks. |

## Important safety and operational notes

1. **No Neon connection was made.** Earlier instruction explicitly deferred any Neon connection until Phase 17 and requires host/database/project identity, disposable status and isolation to be verified before destructive testing. Those facts/configuration were not available in this workspace. “Now Phase 17” does not by itself prove that a target is disposable or authorize destructive operations.
2. **Supabase remains excluded.** Connected status is not authorization; no Supabase tool call or database access occurred.
3. **No deployment occurred.** No Vercel connector call, cloud deployment, DNS change, production secret use or public smoke test occurred.
4. **Do not treat local SQLite/jsdom/build/audit results as Postgres/browser/image/deployment evidence.** Phase 15 and 16 reports preserve exact evidence boundaries.
5. **Possible deployment hardening follow-ups:** pin container image digests at a release build, establish an operator-approved backup/restore runbook, configure HSTS at the actual TLS edge (the API source explicitly leaves this to edge termination), and validate CSP/font/image host requirements in a real browser. These are recommendations, not verified failures.

## Phase 17 outcome

**BLOCKED — no infrastructure/deployment readiness PASS.** Source-level controls and static Compose YAML parse assertions are encouraging but the mandatory isolated PostgreSQL, browser, container, SMTP, backup/restore, and deployment checks have not run. Phase 13 stays **NO-GO**. Do not deploy or claim production readiness until each required item is run on an approved isolated/staging target and its evidence is recorded. Safe code/documentation work can continue without connecting to external infrastructure.
