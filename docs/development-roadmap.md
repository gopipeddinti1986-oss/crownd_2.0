# Development roadmap

## Delivered foundation

See `IMPLEMENTATION_STATUS.md`: app shell, REST/JWT foundation, relational model/migration, basic campaign/product/application/referral/order/reward paths, weighted matching, analytics aggregates and tests.

## Priority 1: security and money correctness

1. Secure-cookie refresh rotation/revocation; email verification and recovery; throttling and abuse controls.
2. Provider adapter for Razorpay, server-side signature verification, signed idempotent webhooks, refunds and reconciliation.
3. Transactional multi-line cart/order, inventory locking, attribution expiry and attribution persistence.
4. Immutable balanced ledger, reward unlock/reversal/approval jobs, audited payout reconciliation and dispute management.

## Priority 2: core product breadth

1. Full creator/brand profiles, verification, social evidence, uploads and portfolio.
2. Complete brand campaign review, creator invitation and collaboration/deliverable revision workflows.
3. Customer storefront/cart/account/order experiences, shipping/tax and notifications.
4. Admin search/review/controls, risk events and audit detail.
5. Durable messaging, in-app/email notification preferences, background worker.

## Priority 3: quality and operations

Automated React tests and Playwright workflows, CI, migrations/rollback testing, observability, rate limits, CSP, production secrets, object storage, performance profiling and independent security review. Only then plan a controlled production launch.
