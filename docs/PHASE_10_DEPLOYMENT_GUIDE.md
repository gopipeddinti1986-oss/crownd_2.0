# CROWND 2.0 — Phase 10 deployment guide

**Purpose:** prepare an operator to deploy the existing application without claiming that a production deployment has been tested. No external account was created, no provider was selected, no service was provisioned, and no deployment was performed during Phase 10.

## 1. Architecture and provider decision

Recommended minimum topology:

```text
Browser --HTTPS--> static SPA / reverse proxy --private network--> FastAPI API
                                                   |                |
                                                   |                +--> TLS PostgreSQL
                                                   |                +--> TLS Redis (shared rate-limit state)
                                                   +--> one notification worker --> SQL outbox --> TLS SMTP

TLS termination, HSTS, certificate renewal, DNS, secret manager, platform logs/alerts,
and encrypted off-host backups are operator/platform responsibilities.
```

Use a same-origin `/api/v1` proxy where practical. It simplifies credentialed CORS and cookie behavior and is already the default Vite/Nginx API path. A separate HTTPS frontend/API origin is supported by exact CORS origins, but must be verified in a real browser; keep the refresh cookie host-only on the API domain, configure `SameSite` deliberately, and update the frontend CSP `connect-src` to the API origin.

The existing repository is compatible with several provider-neutral options:

| Option | Advantages | Tradeoffs / checks before choosing |
|---|---|---|
| Static SPA host + container API/worker host + managed PostgreSQL/Redis/SMTP | Low operational burden for DB patching/backup and simple static asset delivery. Existing guide mentions Vercel as one compatible static-host candidate. | Verify a separate background worker, private networking, TLS DB connection, secret manager, health checks, egress, retention, region/data residency, quotas and current plan terms. Free tiers are not guaranteed and may sleep or omit persistent DB/worker support. |
| One container platform for API, worker and static/Nginx, with managed PostgreSQL/Redis | Fewer deployment surfaces; Dockerfiles and standalone worker suit this model. | Verify multi-service support, migrations as a one-shot job, internal routing, startup/health semantics, volume/backup guarantees and outbound SMTP. |
| Self-managed VM/container host plus managed or self-managed Postgres | Maximum control and potentially low infrastructure complexity at small scale. | Operator owns OS/container patching, TLS, firewalling, PostgreSQL replication/backup/restore, Redis availability, SMTP delivery, alerting and on-call. A Docker volume alone is not a backup. |

**No vendor or cost estimate is selected.** Pricing/free tiers and platform capabilities change; review current provider documentation and contracts, region, quotas, data handling, backup retention, and egress costs before choosing. Avoid adding paid services until workload, data-residency, recovery and service-level needs are agreed. CROWND requires a persistent PostgreSQL DB, TLS-capable shared Redis for production rate limits, one worker, HTTPS ingress, SMTP and off-host encrypted backups; object storage is not required by the current URL-based product image functionality.

## 2. Current validation status

Phase 10 verified local code/config behavior and test suites, not a deployed stack. Docker/Compose, PostgreSQL, `psql`, `pg_dump`, Nginx and browser automation are unavailable in the execution environment. The Compose YAML parses with PyYAML, but `docker compose config`, image builds, container health, Postgres runtime/migrations, external SMTP and host TLS were **not run**. See [`PHASE_10_DEPLOYMENT_AUDIT.md`](PHASE_10_DEPLOYMENT_AUDIT.md) and [`PRODUCTION_READINESS_CHECKLIST.md`](PRODUCTION_READINESS_CHECKLIST.md) for evidence and release gates.

## 3. Requirements and prerequisites

Before a real deployment, obtain explicit project authorization and select a provider/region. Provision, through its normal secret-management path:

- HTTPS ingress with a custom domain/certificate, strict host routing, security headers/HSTS, request-size/time limits, and correct forwarding-header overwrite rules.
- A PostgreSQL database with TLS server identity verification (`sslmode=verify-full`), least-privilege application and backup roles, supported version, durable storage, automated encrypted backups, and a tested restore path.
- TLS Redis (`rediss://`) shared by every API replica for SlowAPI state. Do not substitute `memory://` in production.
- One separately deployed/supervised `python -m app.worker` process with DB and SMTP access.
- SMTP relay with STARTTLS, authentication as required, verified sender/domain, bounce/complaint monitoring and a test mailbox.
- Secret manager/environment injection for `JWT_SECRET`, database/Redis/SMTP credentials, and backup decryption identity. No values belong in Git, image layers, client bundles or tickets.
- Platform log retention/alerts for API/worker errors, latency, database/Redis availability/capacity, and notification outbox backlog/failures.

No real payment gateway is integrated. Demo payment is a local simulation; COD is an administrator-attested offline collection. Online payment, automatic refunds, payouts and shipping are not production integrations.

## 4. Environment variables

Names below match `backend/app/core/config.py` and the supplied Compose template unless marked Compose/edge/frontend. Pydantic loads a local `.env` for development, but production should inject secrets from the platform secret manager, not bake an env file into an image. Production startup rejects missing/insecure core values. `backend/.env.example` is backend local-development configuration; root `.env.example` is **local Compose only**.

| Variable | Required / default | Meaning and production guidance |
|---|---|---|
| `APP_ENV` | `development` | Set `production` in deployed API and worker; enables strict validation, disables FastAPI docs/OpenAPI and applies API CSP. No debug mode is enabled. |
| `APP_NAME` | `CROWND API` | API title; not secret. |
| `DATABASE_URL` | SQLite development URL | Production must be `postgresql+psycopg://...` with TLS `?sslmode=verify-full`. URL-encode credentials; use a distinct app role. Compose constructs a local-only PostgreSQL URL. |
| `JWT_SECRET` | Unsafe development placeholder | Unique random secret, at least 32 characters; generate at least 48 random bytes, store only in secret manager. It signs JWT/refresh MACs and derives the encrypted action-email outbox key. Rotation revokes sessions and can make queued encrypted emails unreadable; drain/re-encrypt or safely fail/re-request them first. |
| `ACCESS_TOKEN_MINUTES` | `15` | Short-lived access JWT lifetime. Positive integer. |
| `REFRESH_TOKEN_DAYS` | `30` | Persistent session expiry; choose retention in line with security policy. Positive integer. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated exact origins. Production requires HTTPS origins, no wildcard, and the frontend origin included. No paths/credentials. |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Absolute frontend origin used in action emails. Must match an allowlisted HTTPS origin in production. |
| `TRUSTED_HOSTS` | Localhost/testserver list | Comma-separated explicit HTTP `Host` allowlist; production must remove local/test hosts and use exact deployed names. |
| `TRUSTED_PROXY_IPS` | Loopback in backend dev; Compose web address in local stack | Addresses/CIDRs permitted by CROWND's forwarded-client-IP policy. Only trust immediate proxy peers under operator control. |
| `FORWARDED_ALLOW_IPS` | Uvicorn loopback default | Uvicorn proxy middleware allowlist, separate from CROWND's IP helper. Set only actual immediate proxy IPs; ensure ingress overwrites `X-Forwarded-*`. Do not set `*` on a reachable API. |
| `COOKIE_SECURE` | Derived from environment | Must be `true` in production; only HTTPS. |
| `COOKIE_SAMESITE` | `lax` | Keep `lax` for same-site use; use `none` only for cross-site HTTPS and with `COOKIE_SECURE=true`, exact CORS/Origin validation, and browser testing. |
| `COOKIE_DOMAIN` | Empty/host-only | Optional bare domain only when explicitly required; prefer host-only API cookies. |
| `RATE_LIMIT_ENABLED` | `true` | Production requires true. |
| `RATE_LIMIT_STORAGE_URI` | `memory://` development | Production requires TLS shared `rediss://host:port/db`; credentials are secret. Confirm TLS certificate validation and access policy. |
| `DB_POOL_SIZE` | `5` | Per-process SQLAlchemy pool base size; choose based on DB connection ceiling. |
| `DB_MAX_OVERFLOW` | `5` | Per-process overflow. Budget total approximately API replicas × (size + overflow) + worker + migration/admin connections. |
| `DB_POOL_TIMEOUT_SECONDS` | `15` | Time waiting for a pooled connection. |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Recycle connection age; align with provider idle limits. |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | PostgreSQL connection timeout. |
| `EMAIL_MODE` | `disabled` | Production must use `smtp`; disabled mode sends nothing. |
| `EMAIL_FROM` | Local placeholder | Verified sender name/address; no secrets. |
| `SMTP_HOST` / `SMTP_PORT` | Empty / `587` | TLS-enabled relay host and port. Production requires host and STARTTLS. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Empty | Relay credentials, if provider requires them; inject as secrets. |
| `SMTP_STARTTLS` | `true` backend default | Production requires true. Do not use local Mailpit SMTP in production. |
| `SMTP_TIMEOUT_SECONDS` | `10` | Per-provider socket timeout (1–120 seconds); retries are bounded. |
| `VERIFICATION_TOKEN_HOURS` | `24` | Email action-token validity. |
| `PASSWORD_RESET_TOKEN_MINUTES` | `30` | Password reset token validity. |
| `ATTRIBUTION_DAYS` | `7` | Referral attribution cookie window; include in privacy disclosures/policy. |
| `MINIMUM_PAYOUT` | `500.00` | Existing product setting; does not enable real payouts. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; avoid debug logs in production. |
| `WORKER_HEARTBEAT_FILE` | `/tmp/crownd-worker-heartbeat` | Worker-local Docker health signal, updated only after a successful DB poll. Not shared with API and not proof that SMTP delivered mail. |
| `VITE_API_URL` (frontend build) | `/api/v1` | Public bundle URL, same-origin by default. Never put tokens, passwords or API secrets in any `VITE_*` value. If set to a separate API origin, update CORS and CSP. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (local Compose) | Local defaults/placeholders | Compose-local DB bootstrap only. Use URL-safe random local password because the Compose URL is assembled from it; never reuse in hosted production. |
| `WEB_BIND_ADDRESS`, `WEB_PORT` (local Compose) | `127.0.0.1`, `8080` | Local-only Nginx bind. Keep bound to loopback unless protected by an explicit TLS ingress/firewall. |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `AGE_RECIPIENT` (backup script) | `./backups`, `30`, required public key | Schedule encrypted backups; keep `AGE_RECIPIENT` public, store private identity separately. |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSFILE` (backup tools) | Operator supplied | libpq connection fields for scripts; password belongs in a mode-0600 `PGPASSFILE`, not command arguments. |
| `AGE_IDENTITY_FILE`, `CONFIRM_RESTORE_TARGET` (restore helper) | Operator supplied | Private recovery identity and exact new local `crownd_restore_test_*` DB confirmation. Restore helper refuses remote hosts. |

There is no separate `SECRET_KEY`; do not invent one unless a future integration requires it. There is no `EMAIL_ENABLED` or `WORKER_ENABLED` setting; use `EMAIL_MODE` and the independently supervised worker process.

## 5. Secret generation, storage and rotation

Generate new secrets outside the repository, for example with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. Keep a separate random JWT secret for each environment. Store it, DB and Redis URLs, SMTP credentials, and backup private identity in the platform's secret manager. Do not add secrets to Docker build args, frontend `VITE_*`, Compose defaults, logs, exception text or Git. The example file contains only recognizable placeholders.

Rotate database/Redis/SMTP credentials through overlapping provider credentials where supported, deploy new values, verify health and revoke old credentials. JWT secret rotation is a coordinated security event: it invalidates access tokens/refresh MACs and all active sessions, and the current outbox key derivation means queued email payloads require controlled draining/re-encryption before changing. Keep an approved recovery procedure and audit record; do not log old/new keys.

## 6. Local Compose stack (development/smoke environment only)

Prerequisites: Docker Engine and Compose plugin. From repository root:

```sh
cp .env.example .env
# Edit .env: replace both local placeholders with distinct URL-safe random values.
docker compose config
docker compose up --build
```

Expected local endpoints: SPA `http://localhost:8080`; API is reachable through same-origin `/api/v1` and is not published directly; local Mailpit inbox `http://localhost:8025` only when started using the `dev-mail` profile. Email is disabled by default. For local Mailpit testing, use `docker compose --profile dev-mail up --build` and set `EMAIL_MODE=smtp`, `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `SMTP_STARTTLS=false` in local `.env`; this is not external SMTP.

Compose includes Postgres, a one-shot `migrate` job, API, worker, web, persistent Postgres volume, health checks, restart policies and a private project network. Only Nginx and optional Mailpit inbox are host-published, both on loopback by default. The web container has a fixed address on a private Compose subnet so Uvicorn's forwarded-header allowlist can identify it; if the subnet conflicts locally, change both the network/IP and proxy allowlists consistently. The stack's `APP_ENV=development`, disabled email and memory rate limiter make it intentionally unsuitable for production. Do not expose it on a public interface or treat Compose as a TLS/secret-manager/backup system.

The app image no longer applies Alembic during Uvicorn startup. Compose's dedicated migration service runs once before API/worker; inspect its exit status/log and verify before opening the web service. For hosted deployments, use the platform's one-shot migration job as below, not simultaneous migration on every API replica.

## 7. Production deployment sequence

1. **Select and threat-model the provider.** Confirm region, privacy/data residency, persistent Postgres/TLS identity, private service-to-service networking, shared Redis, background worker, egress SMTP, secret manager, log retention, backup export and restore, resource/connection limits, pricing and service terms. Do not rely on advertised free tiers as guaranteed.
2. **Provision resources** without copying local database files: PostgreSQL, TLS Redis, API service, worker service, static site or Nginx/frontend, HTTPS DNS/ingress, SMTP and monitoring/backup destinations. Restrict DB/Redis ingress to app/worker/migration identities. Use non-owner least-privilege app credentials; use a separate backup role.
3. **Create the secret set** and non-secret configuration from the table. Set `APP_ENV=production`, explicit `TRUSTED_HOSTS`, actual proxy IPs in both `FORWARDED_ALLOW_IPS` and `TRUSTED_PROXY_IPS`, exact HTTPS CORS/frontend origins, `COOKIE_SECURE=true`, and required TLS DB/Redis/SMTP. Confirm SMTP provider logs do not expose message bodies/tokens. Do not deploy with example values.
4. **Build and scan immutable artifacts.** Build backend with the checked-in hash-pinned runtime lock and frontend with `npm ci`; record source commit, image digest, Node/Python base image digests and scan results. Base image tags in this repository are not digest-pinned; pin/record approved registry digests as part of the actual release pipeline. Test the same images promoted to staging/prod.
5. **Back up before schema change.** Use provider-native encrypted backups plus the encrypted logical backup process described in [`DATABASE_BACKUP_AND_RECOVERY.md`](DATABASE_BACKUP_AND_RECOVERY.md). Confirm a recent restore rehearsal before applying schema changes.
6. **Run Alembic exactly once** using the new backend image and the migration role/production DB secret, as a release job. Example with a container runtime, using secret injection (do not store an env file in the image):

   ```sh
   # Example shape only; `crownd-api:<immutable-tag>` must already be built and scanned.
   docker run --rm --entrypoint alembic \
     --env-file /secure/operator/injected.env \
     crownd-api:<immutable-tag> upgrade head
   ```

   Run `alembic current`/`alembic heads` from the same release image or use the provider's job logs; expect the single repository head `0009_notifications` at this revision. Do not run migrations concurrently in API replicas. Inspect migration output and DB version before routing traffic.
7. **Deploy API and one worker** with the same `DATABASE_URL`, `JWT_SECRET`, SMTP and encryption settings. API uses Uvicorn with proxy-header processing restricted by `FORWARDED_ALLOW_IPS`; API port must be reachable only through trusted ingress. Worker health is a DB-poll heartbeat in Docker; connect platform restart/health monitoring and alerts before relying on it.
8. **Deploy the SPA.** For same origin, build with `VITE_API_URL=/api/v1` and proxy `/api/v1` to API. For separate origin, build with `VITE_API_URL=https://api.example/.../api/v1`, add only the frontend origin to API CORS, test credentialed refresh cookies on supported browsers, and configure the static host CSP to allow that exact API under `connect-src`. Frontend variables are public.
9. **Enable HTTPS at ingress** with TLS 1.2+ (or provider-supported modern TLS), redirect HTTP to HTTPS, explicit host allowlist, HSTS only after confirming HTTPS is universal, request-size/timeouts and correct `X-Forwarded-*` overwrite/real-IP settings. Do not trust arbitrary client-provided forwarded headers. For the same-origin path, retain the Nginx CSP and security headers; at a separate static host, reproduce/review them there.
10. **Smoke-test staging:** `/api/v1/health/live`, `/api/v1/health/ready`, login, refresh, logout/logout-all, reset/verification with a test SMTP inbox, customer cart/checkout using DEMO or COD only, role/ownership checks, worker outbox processing, migration revision, DB/Redis/SMTP monitoring and backup restore. Verify request IDs across edge/API logs. No live-money flow is present.
11. **Promote only after sign-off** on backups, privacy/legal disclosures, incident contacts, alert response, rollout/rollback rehearsal, accessibility/browser E2E, security review and provider terms. No deployment was carried out as part of this guide.

## 8. Database migration, rollback and recovery

Alembic is the sole schema owner. API startup does not call `create_all()` and the new API container CMD does not migrate. Run `alembic upgrade head` once per release as a dedicated job. First verify the migration graph has one head, run fresh/existing upgrade tests, take a backup and check DB/provider compatibility. Expand/contract schema changes around rolling API versions; deploy backward-compatible code before destructive cleanup.

Rollback order: stop/roll back application code to the last schema-compatible image first. Prefer a forward-only migration that fixes the issue. Use a migration downgrade only if that exact downgrade and re-upgrade was tested on the release's PostgreSQL major with realistic copied data and the migration explicitly preserves required data. If schema/data recovery is needed, restore a verified backup to a new database, run consistency checks, then switch the connection through an approved maintenance operation. Never run `alembic downgrade base`, `pg_restore --clean`, or the local restore helper against production without a separately approved and rehearsed procedure.

## 9. Authentication, CORS, proxy and headers

- Access tokens expire after `ACCESS_TOKEN_MINUTES` and are checked against live sessions; refresh token is HttpOnly, `Secure`, narrow-path and SameSite-controlled; logout/reuse/revocation are supported.
- API validates production settings at import/startup and disables interactive docs/OpenAPI in production.
- CORS uses exact origins with credentials; no wildcard. Browser auth endpoints require trusted `Origin` in production. Use HTTPS; cross-site cookies require `SameSite=None; Secure` plus browser validation.
- `TrustedHostMiddleware` rejects hosts outside `TRUSTED_HOSTS`. Set the actual API host and proxy host values. API-level HSTS is not inferred from an internal HTTP hop: configure HSTS at the public TLS-terminating ingress, not at a plaintext internal link.
- API and Nginx set `nosniff`, `no-referrer`, frame denial and Permissions-Policy. Nginx's CSP supports the existing Google Fonts references, HTTPS product images and same-origin API. Review the CSP if assets/API origins change; do not fix CSP errors with a wildcard. Nginx serves hashed assets with immutable caching and SPA fallback.
- Rate limits use SlowAPI with HMAC-obscured IP keys and shared Redis in production. Decorators cover auth, checkout/cart/order mutations, referral click/link operations, admin operations and notification APIs, plus existing analytics/reward routes; this is not a global route limit. Apply explicit limits to new/expensive endpoints and validate Redis behavior/failover. No Redis cluster was available for tests.
- External ingress must overwrite forwarded headers and only its immediate proxy peers belong in `FORWARDED_ALLOW_IPS`/`TRUSTED_PROXY_IPS`. For Nginx behind another edge, configure a narrowly scoped real-IP trust list and confirm IP/rate behavior in staging.

## 10. Logs, health and monitoring

API logs are text key/value records with request ID, method, path (not query), status and duration. Nginx access logs omit query string, referer and IP; Nginx generates a request ID and forwards it. Unhandled API errors return generic JSON; logs contain exception class/path/request ID but not exception text, headers, body, cookies, tokens or SQL values. Uvicorn access logging is disabled to avoid query-string logging. SMTP and worker log fixed error categories/type only.

- `/api/v1/health/live`: process-level liveness only.
- `/api/v1/health/ready`: quick `SELECT 1` database readiness; returns generic 503 when DB query fails; does not test migration version, Redis, SMTP or worker.
- Container API readiness probes DB. Worker writes a local heartbeat only after a successful database poll; Docker healthcheck considers it stale after 30 seconds. This signal does not prove that messages are deliverable or inboxed. `admin/operations` intentionally reports worker as not measured. Non-Docker hosts must monitor worker process health, restart/exit status, logs and outbox age/failure counts themselves.
- Monitor API 5xx and p95 latency, auth/checkout 4xx/429 trends, Postgres availability/replication/storage/connection pool, Redis TLS/availability/latency, SMTP auth/acceptance/bounce/complaint rate, pending/sending/failed outbox age, worker heartbeat/restarts, backup age/restore tests, CPU/memory/disk and certificate expiry.

Use the chosen provider's built-in logging/metrics/alerts if sufficient. No paid monitoring/error-tracking service is required by this repository and none is configured. Avoid sending full request/response or PII to external observability systems.

## 11. Notification worker and email

Start exactly one worker initially with `python -m app.worker`; use the same DB, `JWT_SECRET`, email mode and SMTP settings as the API. It polls bounded batches, claims rows conditionally, recovers stale claims, uses a finite retry/backoff policy, classifies static transient/permanent SMTP categories (auth/5xx/payload errors are terminal; temporary/network errors retry), and responds to SIGTERM/SIGINT between bounded polls. Docker Compose supervises/restarts it; hosted platforms must configure an independent long-running worker and alert on unhealthy/restarted state. Multi-worker/PostgreSQL outbox concurrency was not tested; do not scale workers without dedicated contention/idempotency tests.

SMTP success means provider acceptance only. Configure an isolated test sender/recipient, STARTTLS certificate validation, credentials, timeout, bounce/complaint handling and inbox verification. Phase 10 added mock tests for authentication failure, temporary 4xx, permanent recipient rejection and secret redaction. Real SMTP credentials/receipt were not tested; Mailpit is local-only.

## 12. Backup and restore

Use provider-native backups plus encrypted logical exports, off-site storage, retention, least-privilege credentials and regular restore rehearsal. [`DATABASE_BACKUP_AND_RECOVERY.md`](DATABASE_BACKUP_AND_RECOVERY.md) documents the scripts, `age` key handling, safe local restore rehearsal, frequency/retention recommendations and production recovery sequence. The scripts are not provider-integrated and were not run here because PostgreSQL/age utilities are absent. A persistent volume is not a backup.

## 13. Frontend, performance and dependency maintenance

`frontend/Dockerfile` uses `npm ci`, `npm run build` (TypeScript via `tsc -b`), an unprivileged Nginx runtime and SPA fallback. `VITE_API_URL` is build-time public data. The evidence-based bundle change lazy-loads authenticated admin/referral/reward/notification/charts modules: the Phase 9 largest entry chunk was 864.17 kB (237.09 kB gzip); Phase 10's entry chunk measured 361.93 kB (111.12 kB gzip), about 58% smaller. Recharts is still a separate 381.09 kB chunk and loads when charts render; total code is not removed. No browser performance/Lighthouse measurement was available.

`backend/requirements-runtime.lock` is generated with pip-tools, exact versions and hashes from Python 3.11 and installed in the backend image with `--require-hashes`; runtime requirements exclude pytest/httpx. `frontend/package-lock.json` is installed with `npm ci`. Update locks deliberately, run tests/build and both dependency audits, record source/image digest, and rebuild. Base OCI images use version tags rather than checked-in immutable digests; pin/record digests in the actual release process. npm audit and pip-audit are point-in-time, not a guarantee against future vulnerabilities.

## 14. Troubleshooting

- **Startup config validation:** check only the setting name in the error, inject required environment via secret manager, confirm HTTPS CORS/frontend exact origins, `TRUSTED_HOSTS`, `TRUSTED_PROXY_IPS`, DB `sslmode=verify-full`, `rediss://`, STARTTLS, and nonempty strong secret. Do not print the entire environment.
- **Readiness 503:** investigate PostgreSQL DNS/TLS/CA, connection limit and `alembic_version` with provider tools. Readiness response intentionally does not include a DSN or SQL error.
- **Refresh cookie not present:** confirm HTTPS, `Secure`, SameSite/domain, frontend/API origin relationship, `withCredentials`, exact CORS and trusted `Origin`; use browser devtools without exporting cookie/token values.
- **429s across users:** validate proxy IP propagation and trusted peers. If Uvicorn does not trust the actual immediate proxy, many clients can share one limit key. Do not set forwarded allowlist to `*` as a workaround.
- **Outbox rows stay pending:** inspect worker process/heartbeat, DB poll and worker logs; verify worker shares DB/JWT key and that provider is enabled. `failed` means retry budget exhausted or a permanent error; do not assume provider acceptance was inbox delivery. Do not expose row contents or encrypted payload.
- **Email action links fail after secret rotation:** pending encrypted mail may no longer decrypt; follow the key rotation/runbook and issue a fresh verification/reset link.
- **CSP blocks API/assets:** check same-origin routing and `VITE_API_URL`; update only the exact permitted API/font/image hosts. Do not weaken to unrestricted `*`.
- **Migration job fails:** stop API rollout, preserve logs without credentials, verify backup and actual current revision, inspect SQL on a clone, and use a forward fix or tested rollback plan. Never retry concurrently from every replica.

## 15. Cost and release decision

No current price is quoted: provider region, plan and free-tier terms must be checked by the operator at selection time. A minimal deployment can use one static host, one API service, one worker, managed PostgreSQL, shared TLS Redis, SMTP and provider-native logs/backups. Redis is required by current production config for cross-instance rate limit state; do not add a queue broker, object store, Kubernetes, paid error tracker or real payment provider without a concrete need.

**Current decision:** local development is verified; the architecture is a deployment candidate, but staging/production is **BLOCKED** pending actual PostgreSQL, Docker/container, HTTPS/proxy/browser, backup/restore, real SMTP and worker-health validation plus security/privacy/release sign-off. Do not deploy based solely on this document.
