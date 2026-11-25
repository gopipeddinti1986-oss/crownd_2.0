# Database schema

All primary keys are integer IDs; money uses SQL `NUMERIC`/Python `Decimal`; timestamps are UTC-aware where supported. Alembic config is under `backend/migrations`; run `alembic upgrade head` from `backend/`.

| Table | Purpose and constraints |
|---|---|
| `users` | Unique email, role, active flag, password hash, creation time. |
| `creator_profiles` | Unique user and username, niche/location/platform, self-reported followers/engagement, availability and score fields. |
| `brand_profiles` | Unique owner, name, industry, website, description, verification state. |
| `products` | Brand owner, unique slug, price NUMERIC, stock/status, descriptive fields. |
| `campaigns` | Brand/product, unique slug, reward model/rate/budget, status, descriptive metadata. |
| `applications` | Campaign/creator FKs, unique pair, review status/message. |
| `referrals` | Campaign/creator FKs, unique code, active flag, click counter. |
| `referral_clicks` | Referral FK and timestamp; session hash field reserved for privacy-safe deduping. |
| `orders` | Unique public ID, customer contact, single product/quantity, amount, optional referral, payment/order status. |
| `rewards` | Unique order FK prevents duplicate order reward; creator, amount, status, eligibility timestamp. |
| `ledger_entries` | Append-only intent, reference, user/type/amount/currency; operational posting/reconciliation is incomplete. |
| `payouts` | Creator, amount and request status (admin payout lifecycle partial). |
| `audit_logs` | Actor, action, entity type/id, timestamp. |

Foreign keys, unique constraints, indexed search/status columns and timestamps are included where defined. Product inventory updates/orders and reward records currently need stronger transactional concurrency, multi-line order item modeling, soft deletion, extensive audit evidence and production ledger constraints before financial production use.
