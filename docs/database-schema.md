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
| `orders` | Unique public ID, optional customer FK/idempotency key, customer contact and shipping-address snapshot, compatibility product/quantity, Decimal total, optional existing referral FK, payment/order status. Unique customer/idempotency pair. |
| `order_items` | Order FK and optional product FK plus immutable name/brand/image/unit-price/quantity/line-total snapshots, so future product changes do not rewrite order history. |
| `rewards` / `ledger_entries` / `payouts` | One reward per order and creator references; lifecycle is partial, ledger/payout settlement is not production-ready. |
| `audit_logs` | Actor, action, entity type/id and timestamp. |

Migration `0002_auth_security` conditionally adds verification/session/action-token schema; `0003_customer_commerce` conditionally adds customer commerce columns/tables for both the dynamic `0001` schema and an older pre-commerce database. SQLite fresh upgrade, existing `0002` upgrade, and `0003` downgrade/re-upgrade were verified. PostgreSQL migration/rollback still needs staging verification. Checkout uses atomic conditional stock updates in a DB transaction; there is no separate cart-time reservation. Address data is snapshotted on the order, not stored in an address book. Balanced ledger constraints, payment/refund settlement, order auto-expiry and retention/deletion remain future work.
