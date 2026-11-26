# Phase 11 — Infrastructure validation record

**Date:** 2026-11-25 UTC (per session date)
**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Starting commit:** `1cda7d3996c680f08d94aa79938b841d31a6cc56`
**Status:** In progress / infrastructure-blocked. This record contains only executed results. It is not a production-readiness claim.

## Environment and guardrails

- Workspace: Debian GNU/Linux 12 (Bookworm), x86_64, Linux 6.1 kernel, user UID 1001. Initial branch was the requested development branch and its worktree was clean at `1cda7d3`.
- `docker --version`, `docker compose version`, and `docker info`: all failed with `/bin/bash: docker: command not found` (exit 127). `docker-compose`, Podman, nerdctl, and `/var/run/docker.sock`/`/run/podman/podman.sock` were also absent.
- `psql`, `postgres`, `pg_ctl`, `initdb`, `pg_dump`, `pg_restore`, `createdb`, and `age`: absent. No PostgreSQL binaries were found under `/usr` or `/opt`.
- No Chromium, Chrome, Firefox, Cypress, or existing Playwright installation was present. `frontend` initially had Vitest only and no E2E suite.
- `apt-get` exists and noninteractive `sudo` is available, but this environment has no configured apt sources or cached Docker packages. Docker was not installed: Phase 11's instruction forbids system installs without appropriate permission, and the environment egress policy does not include Docker/OS package repositories. No package manager or daemon configuration was changed.
- The npm registry is available. For a feasibility probe only, Playwright Test and `@sparticuz/chromium` were installed with `npm install --no-save --package-lock=false`; package manifests/lockfile were not changed. Chromium extraction worked, but launch failed before browser startup with `error while loading shared libraries: libnspr4.so: cannot open shared object file`. No browser workflow ran, no screenshot was captured, and missing OS browser libraries were not installed.
- The connected Supabase integration lists one active, healthy PostgreSQL 17 project and its metadata reports an existing CROWND-labelled SQL migration history. Its branch list is empty. Read-only project/service/migration metadata was queried; no SQL query, DDL, DML, API-key/secret read, migration, backup, or deployment was performed. The project is not established as a disposable test target and its migration history is not the repository's Alembic history. Do not use it for application migration/seed/restore tests until the user confirms it is isolated and authorizes the specific test scope.

## Work that was actually executed

### Disposable local SQLite integration smoke

A new, isolated temporary SQLite file was created at `/tmp/crownd-phase11-e2e-20261125.db` after verifying the path did not already exist. It contains only local demo/test data and was not the repository's normal database.

- `alembic upgrade head` executed on that empty DB; revisions `0001_initial` through `0009_notifications` all ran successfully.
- `python seed.py` created its documented local demo brand/creator/campaign/product records. This is SQLite-only evidence, not PostgreSQL evidence.
- A local FastAPI process ran on port 8010 with that DB. `/api/v1/health/ready` returned HTTP 200 and `{"status":"ready","dependencies":{"database":"ok"}}`.
- Login with the repository's local-only seeded brand succeeded with HTTP 200 and role `brand`. The refresh cookie name was `crownd_refresh`; cookie attributes observed included `HttpOnly`, `Path=/api/v1/auth`, and `SameSite=lax`. No cookie/token value was recorded.
- A local Vite process ran on port 5174. SPA, Vite-proxied API readiness and liveness endpoints returned HTTP 200. Vite's API proxy target was overridden to the isolated backend using the new `CROWND_API_PROXY_TARGET` environment setting; browser traffic remained on relative `/api/v1` paths. This is an HTTP smoke check, not browser E2E.
- No changes were made to the existing SQLite DB or any production database.

### Worker process and outbox smoke

Using the same isolated SQLite DB and `EMAIL_MODE=disabled`:

- Inserted one synthetic, non-sensitive pending email-outbox record for the seeded brand, with an intentionally fake payload.
- Ran `python -m app.worker --once --batch-size 20`. It connected to the DB, processed one row, and persisted `status=suppressed`, `last_error_code=provider_disabled`, `attempt_count=1`. This accurately proves disabled mode suppressed the message; it does **not** prove email generation through a live SMTP relay, provider acceptance, delivery or inbox receipt.
- Ran the long-lived worker process. A heartbeat file appeared after the DB poll. Sent SIGTERM through the process supervisor; the worker logged a graceful stop and removed the heartbeat file. Started and stopped it once more to confirm it could restart and poll the isolated DB again.
- Worker retry/exhaustion classification has existing mocked/unit-test evidence from Phase 10. Real SMTP retries, PostgreSQL lock/claim behavior, competing workers, database-restart recovery, and Compose/Docker healthcheck behavior remain unverified.

### Supabase metadata-only observation

The connected Supabase service returned `ACTIVE_HEALTHY` for its PostgreSQL database, pooler, and PgBouncer service; metadata listed PostgreSQL engine 17 and a set of existing CROWND-labelled SQL migrations. No branch was listed. This confirms only that the provider reports a healthy database service and migration metadata. It does **not** confirm connectivity from this app, compatibility with its Alembic revisions, schema/data integrity, or authorization to make changes. No records/customer data were queried.

## Milestone result matrix

| Milestone | Result | Actual evidence / blocker |
|---|---|---|
| 1. Docker environment/config/build | BLOCKED | Docker CLI, Compose plugin, daemon/socket and alternative container runtimes absent; no `docker compose config` or image build executed. YAML parse from Phase 10 is not Compose validation. |
| 2. Full Compose stack/restart/data persistence | BLOCKED | No container runtime. The isolated SQLite API and worker were run as host processes only; PostgreSQL/worker/container restarts and volume persistence were not tested. |
| 3. PostgreSQL/Alembic | BLOCKED for application validation | No local PostgreSQL client/server tools. Supabase DB health metadata was observed, but its existing project is not confirmed safe; no app connection, Alembic run, or data access was attempted. SQLite Alembic upgrade to head passed only. |
| 4. PostgreSQL concurrency | NOT RUN | No PostgreSQL target approved or available. Do not treat SQLite locks/tests as evidence for Postgres row locks, `SKIP LOCKED`, transaction isolation, or simultaneous checkout/outbox handling. |
| 5. Real encrypted backup/restore | BLOCKED | `pg_dump`, `pg_restore`, `createdb`, `age`, and a PostgreSQL target absent. No archive created, encrypted, restored, timed, or integrity-checked. |
| 6. Worker reliability | PARTIALLY VERIFIED | Actual isolated SQLite one-shot processing, disabled-provider suppression, heartbeat creation/removal, graceful SIGTERM and process restart passed. Live SMTP, Postgres failures, Docker health, retry exhaustion under a real provider, and multi-worker concurrency were not run. |
| 7. Browser E2E | BLOCKED | Feasibility probe installed test packages without manifest changes; Chromium could not start because `libnspr4.so` is missing. No customer/creator/brand/admin browser journey or screenshot was run. |
| 8. SMTP | NOT RUN | No SMTP credentials or isolated provider/mailbox available. Mock/unit tests and disabled-provider suppression are not real SMTP validation. |
| 9. Hosting evaluation | DOCUMENTED, NOT SELECTED | See `PHASE_11_HOSTING_EVALUATION.md`. Live prices/terms were not verified and no provider/account was selected. |
| 10. Deployment preparation | PARTIALLY DOCUMENTED | Existing Phase 10 deployment/runbooks reused; no provider-specific config, external secrets, DNS, TLS or service was prepared. Vite proxy-target override was added to support isolated testing without hard-coded API port. |
| 11. Actual deployment | NOT PERFORMED / BLOCKED | No provider selected, cost ceiling approved, safe isolated project confirmed, or credentials configured. Nothing was deployed; no environment was mutated. |
| 12. Production smoke | NOT RUN | No staging/production endpoint or browser test. No localhost/debug/CORS/cookie scan against a real deployment was possible. |

## Safe next actions

1. The user chose a different isolated PostgreSQL target and declined use of the existing Supabase project. No alternate endpoint/secure connection has been supplied yet, so PostgreSQL validation remains blocked. Provide the disposable target through an approved secure mechanism; do not put credentials in chat. Reconcile the local Alembic history before writes.
2. The user chose to defer Docker installation. Provide an approved Docker-capable runner later; no system packages will be installed in this sandbox. Then run `docker compose config`, builds, isolated `up`, health/restart/volume checks, and clean up only newly created test resources. Never remove existing volumes.
3. Provide an environment with PostgreSQL server/client tools and `age`, or authorized package access. Then test fresh/historical Alembic upgrades, backup and restore into a new isolated DB.
4. For browser tests, use a browser-capable runner with Chromium OS libraries (`libnspr4` and other required libraries) or an approved Playwright browser image. Do not claim browser E2E until the real browser starts and workflows execute.
5. Configure an authorized test SMTP relay/mailbox through secret management only, then distinguish message generation, SMTP acceptance, provider delivery and inbox verification.
6. Only after costs, provider scope, and credentials are approved, deploy staging. Public production deployment remains out of scope until explicitly approved and all release gates are met.
