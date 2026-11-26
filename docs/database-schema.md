# Database schema

Money uses SQL `NUMERIC`/Python `Decimal`; timestamps are UTC-aware where supported. Use `alembic upgrade head` from `backend/`; application import no longer creates/mutates production schema implicitly.

| Table | Purpose and constraints |
|---|---|
| `users` | Unique email, role, active flag, Argon2id/legacy password hash, `email_verified`, creation time. Existing rows migrate as verified for compatibility; all new signups explicitly start unverified. |
| `auth_sessions` | Opaque session ID, user FK, **current refresh-token digest only**, fixed absolute expiry, revocation timestamp and last-used time; cascade deletes with account. |
| `auth_action_tokens` | User FK, constrained purpose value (`verify_email` or `password_reset`), random token digest, expiry, one-use timestamp. Raw tokens are never persisted. |
| `creator_profiles` | Unique user and username, niche/location/platform, self-reported metrics, availability and score fields. |
| `brand_profiles` | Unique owner, name, industry, website, description, verification state. |
| `products` | Brand owner, unique slug, regular and optional sale `NUMERIC` price, stock/status/descriptions, JSON image gallery and specifications. |
| `campaigns` | Brand/product, unique slug, reward model/rate/budget/status. |
| `applications` | Campaign/creator FKs, unique pair, review status/message. |
| `referrals` / `referral_clicks` | Campaign/creator FKs, unique code, active flag/counter; click timestamp and privacy-safe session-hash placeholder. |
| `carts` / `cart_items` | One persistent cart per signed-in user; unique `(cart_id, product_id)`, positive quantity, indexed product/cart FKs. Inventory is not reserved while in cart. Guest carts are not supported. |
| `orders` | Unique public ID, optional customer FK/idempotency key, contact and address snapshot, compatibility product/quantity, Decimal total/currency, optional referral FK, separate order/payment statuses and method (`demo`, `cod`, `online`, or migrated `legacy`), transaction reference/notes, confirmation time/actor. Unique customer/idempotency pair; checks constrain payment method/status. |
| `order_items` | Order FK and optional product FK plus immutable name/brand/image/unit-price/quantity/line-total snapshots, so future product changes do not rewrite order history. |
| `payment_attempts` | Order FK, unique attempt number/idempotency key, payment method/status, fixed-precision amount/currency, optional reference/notes, creation/confirmation time and confirming user. Local demo attempts are not provider transactions; COD collection updates its checkout attempt once. |
| `rewards` / `ledger_entries` / `payouts` | One reward per order and creator references; `rewards.is_demo` distinguishes non-payable simulated rewards; demo records are excluded from revenue/payout eligibility. Lifecycle and actual payout settlement remain partial. |
| `audit_logs` | Actor, action, entity type/id and timestamp. |
| `notification_preferences` | One row per user; global in-app/email defaults and explicit per-category overrides. Security/action emails can be marked essential and ignore opt-out where required. |
| `notifications` | Recipient FK, category, bounded plain-text title/body, allowlisted internal action route, read timestamp and unique `(recipient_id, event_key)` idempotency key. |
| `email_deliveries` | Recipient FK, category, authenticated ciphertext of subject/body, essential flag, unique `(recipient_id, event_key)`, status/attempt count/next-attempt/claim/delivery timestamps and static error code. No recipient address or provider response is copied into the queue or admin view. |

Migration `0002_auth_security` adds auth state, `0003_customer_commerce` adds customer commerce, and `0004_payment_options` adds payment metadata/attempts and demo-reward marker. The payment migration is conditional for the repository's dynamic `0001` metadata history and backfills older orders as `legacy` (without asserting they were demo or genuine). Fresh SQLite upgrade and `0004` downgrade/re-upgrade passed. PostgreSQL migration/rollback still needs staging verification. Checkout uses atomic conditional stock updates; no cart-time reservation exists. Address data is snapshotted, not an address book. Refund/partial-refund, automatic unpaid-order expiry, and retention/deletion remain future work. Migration `0009_notifications` adds the recipient-scoped notification inbox, preferences and encrypted SQL mail outbox. The outbox uses Fernet with a key derived from `JWT_SECRET`; rotating that secret while messages are pending makes them undecryptable, so drain/handle the queue before rotation. Downgrade retains notification tables and history intentionally. SQLite and historical-upgrade paths are tested; PostgreSQL remains unverified.
