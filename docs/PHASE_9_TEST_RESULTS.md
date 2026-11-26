# Phase 9 — Executed test results

**Date:** 2026-11-25 (UTC)
**Branch:** `arena/e6c9b4f7-crownd-2-0`
**Scope:** local Phase 9 verification; not a production-readiness statement.

## Final automated checks

| Command/check | Result | Notes |
|---|---:|---|
| `backend/.venv/bin/pytest -q` (run from `backend/`) | **68 passed** | Full backend suite after the final regressions and auth/admin changes; one upstream Starlette/httpx deprecation warning. |
| `npm test -- --run` (from `frontend/`) | **38 passed, 9 files** | Recharts emitted existing zero-width/height chart warnings in jsdom; tests passed. |
| `npm run lint` | **passed** | ESLint. |
| `npm run build` | **passed** | Includes `tsc -b` and Vite production build. Vite reports the main JS chunk at 864.17 kB (>500 kB advisory). |
| `npm run typecheck` | **not a configured script** | This command failed because `package.json` has no `typecheck` script. TypeScript checking did run successfully as part of `npm run build` (`tsc -b`). |
| `backend/.venv/bin/python -m compileall -q app tests` | **passed** | Backend source and tests compiled. |
| `git diff --check` | **passed** | No whitespace errors at time of check. |
| `npm audit --audit-level=high` | **0 vulnerabilities reported** | npm audit only; not a complete security assessment. |
| Targeted tracked-source secret/debug-pattern grep | **no matches** | Looked for common private-key/API-key patterns and console/debugger/breakpoint patterns in tracked source. Not a complete secret scanner. |

### Focused regression and concurrency runs

- `tests/test_commerce.py::test_suspended_brand_content_is_hidden_and_cannot_be_purchased` and `tests/test_commerce.py::test_phase5_mixed_cart_creates_idempotent_item_attributed_rewards_for_multiple_creators`: **2 passed** after adding final product/category/brand and stock/order assertions.
- Combined focused run of concurrent refresh, existing refresh-cookie rotation, suspended-brand, mixed-brand, and admin lifecycle tests: **5 passed**.
- The concurrency regression uses two synchronized refresh requests against a temporary SQLite file. Its observed result after the fix was one `200`, one `401`, and a revoked session. Before the fix, the same synchronized reproduction returned two `200` responses and left the session unrevoked. The regression passed once in the full suite, once in focused checks, and in five additional repeat runs. This is a narrow SQLite test, not a PostgreSQL or multi-process deployment test.
- Non-finite validation checks executed earlier in this phase: NaN/Infinity product price, campaign reward rate, and campaign budget payloads each raised Pydantic `ValidationError`.

## Migration and database checks

- Local pre-existing SQLite DB: Alembic current revision `0005_referral_attribution`; repository head `0009_notifications`. The working DB was not migrated.
- Disposable DB copy: `DATABASE_URL=sqlite:////tmp/crownd-phase9-validation.db ./.venv/bin/alembic upgrade head` completed successfully from `0005` to `0009`.
- On the upgraded copy: SQLite integrity check `ok`; no foreign-key violations; 35 tables. Basic integrity queries found zero negative stock, negative order amount, nonpositive order-item quantity, missing order customer email, orphan conversion/reward, or ledger reward reference. The sample had no order/conversion/reward/ledger rows, which materially limits these data checks.

## Unavailable, not run, or incomplete

- **PostgreSQL:** `psql`, `postgres`, `pg_ctl`, Docker and Podman are unavailable. No PostgreSQL migration, integration, lock, constraint, query-plan, or performance result is claimed.
- **Browser E2E:** Python Playwright and frontend Playwright/Cypress packages are absent. No real browser journey/accessibility run occurred. Vitest component/API tests are not browser E2E.
- **Python dependency/SAST scans:** `pip-audit` and Bandit are not installed; neither scan ran. npm audit's zero result is limited to npm's audit database and lockfile resolution.
- **External integrations:** no real payment gateway/refunds, payout settlement, SMTP provider receipt, or carrier integration was exercised. Demo payment is simulated; COD collection behavior is only application logic.
- **Concurrency/load:** only the synchronized refresh-token race was exercised locally. No checkout-vs-checkout final-stock test under PostgreSQL, multi-worker outbox race, admin multi-actor race, load/stress, or production concurrency test is claimed.
- **Independent review:** no independent penetration test, professional security audit, formal privacy/legal review, or production-readiness assessment was performed.

## Warnings and command notes

- Backend emits `StarletteDeprecationWarning` that using httpx with `starlette.testclient` is deprecated and suggests `httpx2`.
- Frontend chart tests emit Recharts warnings because jsdom containers report zero width/height. They did not fail tests.
- Vite build emits a chunk-size advisory; current largest generated JS chunk is 864.17 kB before gzip (237.09 kB gzip).
- A separate `npm run typecheck` invocation was attempted and failed because that script does not exist. The build's `tsc -b` succeeded, so this is a script-name/configuration gap rather than a TypeScript build failure.

These results show that the listed local checks passed; they do not prove system-wide correctness or production readiness. See [`PHASE_9_QA_AUDIT.md`](PHASE_9_QA_AUDIT.md) for defect reproduction/root-cause/fix details and residual risks.
