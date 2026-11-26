# Phase 11 — Hosting evaluation (provider-neutral; no provider selected)

**Date:** 2026-11-25 UTC
**Decision status:** Evaluation only. No account, project, plan, DNS, secret, paid service, or deployment was created. Prices and current free-tier conditions were not verified; they change by provider, region and date.

## Application requirements found in the repository

- **Frontend:** Vite-built React SPA; Nginx container supports SPA fallback and same-origin `/api/v1` reverse proxy. Static hosting is feasible if it can route API requests to the backend or the API CORS/CSP/cookie origins are deliberately configured.
- **API:** FastAPI/SQLAlchemy with Alembic. Production settings require PostgreSQL using TLS certificate/hostname verification (`sslmode=verify-full`), a strong injected `JWT_SECRET`, explicit hosts/proxies, HTTPS CORS/frontend origin, secure cookies, TLS Redis for shared rate limits, and SMTP/STARTTLS.
- **Worker:** independent continuously running `python -m app.worker`, sharing DB and `JWT_SECRET` with API. A static-only/serverless request function is not a substitute; provider must support an always-on background process or an equivalent supervised long-running container.
- **Database:** persistent PostgreSQL is mandatory. User sessions, orders, referrals, conversion/reward/ledger records and outbox are in SQL. No object-store feature is required by the current product. Backups must be encrypted/off-host and restores rehearsed.
- **Other services:** shared TLS Redis and SMTP are required by production config; TLS termination, domain/DNS, logs/alerts, secret management and backup storage must be supplied. Real payment integration is absent; checkout is demo/COD only.

## Candidate architectures

| Candidate | Fit and operational tradeoffs | Cost considerations / current evidence |
|---|---|---|
| **A. One small Linux VM with Docker Compose**: TLS ingress, web, API, one worker, PostgreSQL and Redis containers; encrypted off-host backups and external SMTP. | Lowest service count and potentially the lowest fixed bill; Compose file already models the local services. One VM is a single failure domain; operator owns host patching, TLS, firewall, disk, DB upgrades, backups, monitoring and restoration. Persistent local volume alone is not resilience. This repository's Compose/runtime has not yet been executed, so this is only a candidate. | VM + persistent disk + off-host backup storage + domain + SMTP; possible egress/backup costs. No price checked. May be student-friendly for a non-sensitive staging demo if resource sizing, backup target and recovery owner are accepted. Not recommended for real customer data before PostgreSQL/Docker/recovery validation. |
| **B. Static frontend host + long-running container host for API and worker + managed PostgreSQL/Redis + SMTP relay** | Good separation: static assets are cheap/simple, managed DB reduces routine DB operations, API and worker remain normal containers. Must verify the app host supports one-shot migrations, private/TLS DB/Redis access, a persistent worker, graceful shutdown, health/restart policy, logs and SMTP egress. Cross-origin frontend/API adds cookie/CORS/CSP complexity; same-origin proxy is preferable. | Recurring app compute, managed database, Redis, email and backup/egress components may exceed a single VM. Static hosting may offer low-cost/student-friendly plans but limits, sleeping, build quotas and commercial terms can change. No plan/price verified. Best candidate for a later staging deployment if service capabilities and cost are approved. |
| **C. Existing Supabase PostgreSQL + separate API/worker host + static frontend** | PostgreSQL is technically compatible in principle via a TLS PostgreSQL connection, but local Alembic revisions and Supabase SQL migrations must not be assumed interchangeable. Connection-pooler mode, migration connection, SSL hostname verification and connection limits require testing. Supabase Auth is not a drop-in replacement: this app has its own session tables, JWT cookies and SQL outbox. | Managed database reduces DB operations but app compute, worker, Redis, SMTP and backups remain. Project plan, branch availability, limits, region/data residency, costs and network access must be checked. Read-only connector metadata during Phase 11 showed an existing healthy PostgreSQL 17 project with CROWND-labelled SQL migrations and no listed database branches. Its purpose/isolation is unconfirmed; it was not touched and is **not selected as a test or deployment target**. |

## Recommendation

1. **Near-term validation:** use a disposable PostgreSQL instance and a Docker-capable CI/VM runner, not the existing connected Supabase project until its owner confirms it is isolated and authorizes test writes. Keep all test data synthetic.
2. **Low-cost staging candidate:** compare Candidate A (one small VM/Compose stack) against Candidate B (static hosting + one API/worker container host + managed Postgres/Redis). Candidate A likely has fewer line items but much greater operator risk; Candidate B is easier to recover/patch if its plan supports worker processes and private managed services. Choose based on total monthly cost, region, quotas, backups and on-call ownership, not headline/free-tier claims.
3. **Production direction:** prefer managed PostgreSQL with tested encrypted backups/restore, a separately supervised API and worker, shared TLS Redis, HTTPS ingress and platform monitoring. A VM can still be appropriate if an operator accepts and tests the operational burden. No production recommendation can be finalized until runtime, restore, security, traffic and privacy requirements are validated.
4. **No public deployment now:** no provider was selected, exact costs/terms were not fetched, no production-like PostgreSQL tests were run, and no public deployment authorization/credentials were supplied. Payments remain simulated/COD only.

## Cost and region checklist before decision

- Quote all services in the required region and currency, including taxes, storage, backups, snapshots, egress, build minutes, always-on worker compute, Redis, SMTP volume, domain and support.
- Confirm what happens at quota/free-tier exhaustion, idle/sleep policies, account verification/age requirements, payment-card requirements, cancellation/retention and data export.
- Confirm PostgreSQL major version, TLS/CA procedure, connection limit/pooler, backup/PITR retention, restore fees, data-residency region, incident response, and whether a test branch is included or costs extra.
- Confirm worker process duration/restarts, migration job semantics, private network access, log retention/alerts, health checks, outbound SMTP rules and custom-domain TLS.
- Document an owner-approved monthly ceiling and RPO/RTO before creating infrastructure. No current price or free-tier guarantee is stated in this document.
