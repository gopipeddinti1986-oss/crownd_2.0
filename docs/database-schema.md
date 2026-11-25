# Database schema

Money uses SQL `NUMERIC`/Python `Decimal`; timestamps are UTC-aware where supported. Use `alembic upgrade head` from `backend/`; application import no longer creates/mutates production schema implicitly.

| Table | Purpose and constraints |
|---|---|
| `users` | Unique email, role, active flag, Argon2id/legacy password hash, `email_verified`, creation time. Existing rows migrate as verified for compatibility; all new signups explicitly start unverified. |
| `auth_sessions` | Opaque session ID, user FK, **current refresh-token digest only**, fixed absolute expiry, revocation timestamp and last-used time; cascade deletes with account. |
| `auth_action_tokens` | User FK, constrained purpose value (`verify_email` or `password_reset`), random token digest, expiry, one-use timestamp. Raw tokens are never persisted. |
| `creator_profiles` | Unique user and username, niche/location/platform, self-reported metrics, availability and score fields. |
| `brand_profiles` | Unique owner, name, industry, website, description, verification state. |
| `products` | Brand owner, unique slug, price NUMERIC, stock/status and descriptions. |
| `campaigns` | Brand/product, unique slug, reward model/rate/budget/status. |
| `applications` | Campaign/creator FKs, unique pair, review status/message. |
| `referrals` / `referral_clicks` | Campaign/creator FKs, unique code, active flag/counter; click timestamp and privacy-safe session-hash placeholder. |
| `orders` | Unique public ID, customer contact, one product/quantity, amount, optional referral, payment/order status. |
| `rewards` / `ledger_entries` / `payouts` | One reward per order and creator references; lifecycle is partial, ledger/payout settlement is not production-ready. |
| `audit_logs` | Actor, action, entity type/id and timestamp. |

Migration `0002_auth_security` conditionally adds verification/session/action-token schema for the repository's existing dynamic `0001` migration and preserves existing accounts as verified. Review it against snapshots before applying to external databases. It handles an existing database and a fresh current metadata-created DB. Foreign keys/uniqueness are present but broader ORM relationships, row-locked stock/reservation, full order line-items, balanced ledger constraints, immutable DB enforcement and data-retention/deletion are future schema work.
