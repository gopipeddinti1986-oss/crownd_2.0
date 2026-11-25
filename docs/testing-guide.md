# Testing guide

Backend test suite uses pytest + FastAPI TestClient and an isolated in-memory SQLite database. Run from `backend/`: `.venv/bin/pytest -q`. It covers creator/brand registration, protected role behavior, duplicate account/application rejection, campaign publication and acceptance, referral generation/click, simulated order->pending reward, and Decimal calculations.

Frontend unit tests run with `cd frontend && npm test` (reward and INR display helpers); production typecheck/build: `npm run build`. These are not end-to-end tests. There is no Playwright suite or browser checkout workflow yet. Payment provider webhooks, refunds, payout approval, concurrency races, migrations against PostgreSQL and load/security testing are not verified. Re-run builds/tests after each change; do not infer production readiness from passing local tests.
