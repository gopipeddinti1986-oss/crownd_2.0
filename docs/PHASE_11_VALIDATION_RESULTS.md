# Phase 11 — Validation results

**Date:** 2026-11-25 UTC
**Starting commit:** `1cda7d3996c680f08d94aa79938b841d31a6cc56`
**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Overall:** Some isolated host-process/SQLite checks passed; mandatory Docker, PostgreSQL runtime, actual backup/restore, SMTP and browser E2E remain blocked or unrun. No staging/production deployment occurred.

## Executed results

| Area | Executed command / operation | Result |
|---|---|---|
| Git preflight | `git status --short`, `git branch --show-current`, `git log -10 --oneline`, `git remote -v` | Worktree clean at start; branch `arena/e6c9b4f7-crownd-2-0`; HEAD `1cda7d3`; origin points to the requested repository. |
| Docker CLI | `docker --version`; `docker compose version`; `docker info` | All three returned `docker: command not found`, exit 127. No daemon socket or alternatives found. No install performed. |
| OS/install feasibility | `uname -a`, `/etc/os-release`, `id`, executable/package/socket searches, `sudo -n true`, `apt-cache policy docker.io`, apt source/cache inspection | Debian 12 x86_64; uid 1001; noninteractive sudo works but apt has no configured sources/cached Docker package and egress policy excludes OS/Docker repositories. Docker installation was not authorized/performed. |
| PostgreSQL tools | command lookup and executable search for `psql`, `postgres`, `pg_ctl`, `initdb`, `pg_dump`, `pg_restore`, `createdb` | Not present. No local PostgreSQL server or utilities. |
| Supabase provider metadata | Connected Supabase `list_projects`, `list_branches`, `get_project_health` for `db`, `pooler`, `pg_bouncer`, `list_migrations` | One existing project reported PostgreSQL engine 17 and all three services `ACTIVE_HEALTHY`; it has CROWND-labelled SQL migration history and no listed branches. Metadata only; no raw SQL/row access or writes. Project is not confirmed isolated. |
| Fresh isolated migration | `DATABASE_URL=sqlite:////tmp/crownd-phase11-e2e-20261125.db ... ./.venv/bin/alembic upgrade head` | Fresh SQLite migration sequence `0001_initial` through `0009_notifications` completed. This is not PostgreSQL validation. |
| Local seed | `DATABASE_URL=... ./.venv/bin/python seed.py` | Seeded documented local demo brand/creator/product/campaign data in that disposable temp DB. No other DB touched. |
| API readiness and auth | Backend Uvicorn on port 8010 against the temp SQLite file; Python `httpx` calls to `/api/v1/health/ready` and `/api/v1/auth/login` with local demo brand | Readiness HTTP 200, DB dependency `ok`; seeded brand login HTTP 200/role `brand`; refresh cookie name/attributes were inspected without recording token values. This does not validate PostgreSQL or browser cookies. |
| Frontend/API HTTP smoke | Vite on port 5174 with `CROWND_API_PROXY_TARGET=http://127.0.0.1:8010`; `curl` to `/`, `/api/v1/health/ready`, `/api/v1/health/live` | SPA and proxied readiness/liveness each returned HTTP 200. No browser executed the pages. |
| Worker delivery path | Inserted one synthetic pending outbox row in the isolated SQLite DB; `DATABASE_URL=... EMAIL_MODE=disabled ... python -m app.worker --once --batch-size 20` | Worker processed one; row persisted as `suppressed`, `provider_disabled`, `attempt_count=1`. This proves disabled-provider handling, not SMTP delivery. |
| Worker heartbeat/restart | Ran `python -m app.worker --poll-seconds 0.5 --heartbeat-file /tmp/crownd-phase11-e2e-worker-heartbeat`; checked file, stopped via SIGTERM, checked file removal, started/stopped a second time | Heartbeat appeared after a DB poll; graceful stop removed it; second process started and stopped. Host-process/SQLite only, not Compose/Postgres or failure-injection coverage. |
| Playwright feasibility | `npm install --no-save --package-lock=false @playwright/test@1.65.1 @sparticuz/chromium@158.0.0`; extracted Chromium; attempted Playwright `chromium.launch(...)` | npm install reported zero vulnerabilities and did not modify manifests/lockfile. Browser launch failed (exit 127) because `libnspr4.so` is absent. No E2E workflow ran and no screenshots were captured. Ran `npm ci` afterward to restore the locked frontend dependency tree. |
| Existing tests | Phase 10 baseline at commit `1cda7d3`: backend 74 passed; frontend 38 passed; ESLint/build/audits passed. Phase 11 proxy config changed after this baseline. | The old results remain historical; this Phase 11 turn reran frontend validation after its Vite config change and records the actual result below. No PostgreSQL/browser implications. |

### Phase 11 frontend validation after proxy-target setting change

- `npm test -- --run`: **38 passed** across 9 files.
- `npm run lint`: passed.
- `npm run build`: passed (`tsc -b` plus Vite production build).
- `git diff --check`: passed. Existing Recharts jsdom zero-dimension warnings appeared during component tests; no browser measurement was made.

## Not executed — do not report as passed

- `docker compose config`, `docker compose build`, `docker compose up`, `docker compose ps/logs`, container restarts, health checks and volume persistence.
- PostgreSQL application connection, fresh/existing Alembic upgrade, downgrade/re-upgrade, triggers/constraints, business flows, concurrent checkout/stock/referral/reward/session/outbox, DB restart and recovery.
- `pg_dump`, encrypted archive creation/integrity, `age` encryption, restore into a second PostgreSQL database, timings, record counts, FK checks or app connectivity to a restored PostgreSQL DB.
- SMTP connection/auth/TLS/provider acceptance/delivery/inbox verification. No credentials were requested or invented.
- Browser Playwright workflows (customer, creator, brand, admin, referral conversion, COD, cancellation, account restriction). Browser did not start.
- Public/staging deployment, provider-specific config/secrets/DNS/TLS, production smoke tests, live monitoring or costs.

## Blockers and exact next procedure

1. Obtain an approved disposable PostgreSQL target or explicit confirmation that the existing connected Supabase project is isolated and authorized for the stated test writes. Its CROWND migration history is not the local Alembic history; first compare schema/migration state without mutating it. Do not run migrations or seed data in that project before approval.
2. Provide an approved Docker-capable runner. Alternatively, explicitly authorize system-level Docker installation and configure OS package access; current Debian package sources are absent and this environment's outbound allowlist does not include Docker/OS package repositories. Then run `docker compose config`, build, and bring up only an isolated test project. Inspect volumes before any teardown; never remove an existing volume.
3. Install/provide PostgreSQL and `age` tools only in an approved environment. Use a new disposable DB and synthetic data. Run Alembic fresh and historical paths, then backup to an encrypted file, verify it, restore to a *different new* DB and compare schema/counts/FKs/representative records.
4. Use a browser runner/container with Chromium plus OS shared libraries (including `libnspr4`). Add/keep Playwright tests only after browser launch and an actual workflow execute; produce trace/report/screenshots as artifacts without committing large browser binaries.
5. Configure an explicitly approved test SMTP mailbox through secret management and measure message generated, SMTP accepted, provider-delivered and inbox-verified as separate results.
6. Choose a hosting provider only after live current pricing, region, quotas, data residency, backup and worker compatibility are checked and an operating-cost ceiling is approved. Do not deploy publicly in this phase without the necessary authorization and credential path.
