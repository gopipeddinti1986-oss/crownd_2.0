# API overview

Base path: `/api/v1`. Interactive OpenAPI: `/docs`. Authenticated requests use `Authorization: Bearer <access_token>`.

| Method/path | Access | Behavior |
|---|---|---|
| POST `/auth/register`, `/auth/login` | Public | Create supported creator/brand/customer accounts; login returns access JWT. |
| GET `/auth/me` | Auth | Current account/profile. PUT `/creators/me` updates creator basics. |
| GET `/creators` | Auth | Search/filter list. GET `/ai/matches/{campaign_id}` | Brand owner/admin; weighted reasons and scores. |
| GET/POST `/products` | Public read / brand write | List active items; create product. |
| GET/POST `/campaigns` | Public listing / brand create | Browse/create draft campaign. GET `/campaigns/{id}`. PATCH `/campaigns/{id}/status` is owner/admin guarded. |
| POST `/campaigns/{id}/applications` | Creator | Apply once to published campaign. GET `/applications`; PATCH `/applications/{id}` for campaign owner/admin review. |
| GET `/referrals/me` | Creator | Referral codes/links for accepted applications. GET `/r/{code}` | Track a click and return campaign/product destination metadata. |
| POST `/orders` | Public checkout API | Single product order; code is validated. `simulate_payment: true` only models local success when simulator + development. |
| GET `/orders` | Auth | Orders scoped to customer, brand, creator, or admin. |
| GET `/rewards/me`, POST `/payouts` | Creator | Reward list and threshold-checked payout request. |
| GET `/analytics/overview`, `/analytics/timeseries` | Auth | Database-derived role-scoped counts and paid revenue. |
| GET `/admin/users`, `/admin/audit-logs` | Admin | Basic administrative read endpoints. |

Bodies use JSON. Errors use FastAPI `{ "detail": ... }` with appropriate HTTP status. This API is versioned but currently does not provide a general pagination envelope, idempotency keys for checkout, full payment endpoints, order mutation/refunds, or complete admin workflows.
