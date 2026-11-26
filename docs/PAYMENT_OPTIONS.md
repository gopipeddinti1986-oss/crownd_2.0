# Payment options and order lifecycle

## Product decision and boundaries

CROWND Phase 3 does **not** integrate a payment gateway. There are no provider SDKs, external payment requests, webhooks, or real online-money transactions. `payment_method=online` is rejected by the API and disabled in checkout with the label **“Online payment coming soon.”** Do not treat a demo payment as a genuine settlement or release a real product/service on its basis.

The current API keeps the provider-shaped information on `Order` and records individual events in `PaymentAttempt`. A future provider can add its own adapter and verified webhook processor without changing cart price calculation or order snapshots; no provider integration exists now.

## Customer options

### Demo payment

- Customer chooses **Demo payment**. The UI explicitly states: “Demo payment mode. No real money will be charged.”
- `POST /checkout` accepts only the payment method and shipping data; clients cannot post a payment result, amount, reference, or payment status.
- The backend generates a `DEMO-…` reference and runs the in-process simulation. Success sets payment `paid` and order `confirmed`; failure sets payment `failed`, order `cancelled`, and restores reserved stock in the same transaction.
- Checkout idempotency applies to both the order and payment attempt. Replaying the same customer/key returns the recorded outcome and cannot process a second demo payment.
- For local automated failure-path testing only, send `X-Demo-Payment-Test-Failure: true`. This flag can only cause a failure (never a success claim) and is rejected when `APP_ENV=production`.
- Successful referral-attributed demo orders may create a pending `Reward` marked `is_demo=true`. These demo rewards are displayed as simulated/non-payable and excluded from genuine revenue and payout eligibility.

### Cash on delivery (COD)

- Checkout creates an order with `payment_method=cod`, `payment_status=unpaid`, and `status=confirmed`. A payment attempt records the amount/currency and that collection is due on delivery. No payment reference or collection is inferred at checkout.
- Authorized administrators update order fulfillment through `PATCH /orders/{order_id}/status`. COD can proceed through `processing → shipped → delivered` while still unpaid.
- After delivery, an administrator uses `POST /admin/orders/{order_id}/collect-payment`. The server requires a delivered COD order that is still unpaid, marks it `paid`, creates an internal `COD-COLLECT-…` collection reference, records collector and timestamp, appends an audit event, and rejects duplicate collection requests.
- This records an administrator attestation of offline cash collection, not a digital transaction or independent proof of cash receipt. A referral reward, if eligible and within campaign budget, is created as a regular pending reward at this step; no payout is executed.
- COD may be cancelled while pending/confirmed and unpaid. Cancellation voids the collection obligation (`not_required`) and restores inventory once. Delivered orders cannot be cancelled via the normal cancellation route.

### Online payment

Online payment is shown as disabled and labelled **“Online payment coming soon.”** The server also rejects it. There is no fake online flow, provider, SDK, transaction, or webhook.

## Stored payment information

`Order` retains the fixed-precision `NUMERIC(12,2)` total, `currency`, `payment_method`, `payment_status`, optional transaction reference, confirmation timestamp/user, and payment notes. `PaymentAttempt` records order FK, attempt number, owner-scoped idempotency key, method, status, fixed-precision amount/currency, reference, notes, creation/confirmation time, and confirming user. COD collection updates the original COD attempt rather than creating a second collection. Database uniqueness/check constraints prevent duplicate attempt numbers/keys and invalid method/status values.

Legacy orders are migrated as `payment_method=legacy`; their old payment statuses are preserved. Existing rewards linked to those legacy orders are conservatively marked `is_demo=true` because prior simulator provenance cannot be verified; this prevents historical simulator records from becoming payout-eligible.

## State transitions

Order and payment state are separate:

| Event | Order status | Payment status | Inventory |
|---|---|---|---|
| Demo success | `confirmed` | `paid` (simulated; `DEMO` reference) | Deducted once |
| Demo failure | `cancelled` | `failed` | Restored in the checkout transaction |
| COD checkout | `confirmed` | `unpaid` | Deducted once |
| COD fulfillment | `processing`, `shipped`, `delivered` | remains `unpaid` | No additional changes |
| Admin confirms delivered COD cash | remains `delivered` | `paid` | No additional changes |
| Unpaid COD cancellation before fulfillment | `cancelled` | `not_required` | Restored once |

Fulfillment status updates are administrator-only and audited. Payment collection is admin-only. Customers can read only their own order details and cannot mutate payment records. Payment amount/status/reference fields are not writable on customer checkout.

`paid` on a DEMO order means “simulated success” only. Revenue analytics and payout eligibility explicitly exclude demo and legacy payment methods. There is no current refund or partial-refund execution workflow; paid orders cannot be cancelled through the unpaid cancellation path.

## API operations

- `POST /checkout` — authenticated customer; requires `Idempotency-Key`, `shipping_address`, and `payment_method` (`demo`, `cod`, `online`). Online is rejected.
- `GET /orders?view=customer`, `GET /orders/{public_order_id}` — owned customer order history/details.
- `GET /admin/orders` — admin-only filters: `q`, `status`, `payment_status`, `payment_method`, paging.
- `GET /admin/orders/{public_order_id}` — admin-only order/payment details and attempt history.
- `PATCH /orders/{public_order_id}/status` — admin-only validated fulfillment transitions.
- `POST /admin/orders/{public_order_id}/collect-payment` — admin-only COD collection after delivery.
- `POST /admin/orders/{public_order_id}/cancel` — admin cancellation for eligible unpaid orders.
- Customer cancellation remains `POST /orders/{public_order_id}/cancel` for their own eligible unpaid order.
- Legacy guest single-item `POST /orders` is retired and returns `410 Gone`.

## Limitations / future integration

No saved payment instrument, payment provider, signed webhook, charge/refund/partial-refund path, COD carrier confirmation, shipping/tax quote, automatic reservation expiry, or payment reconciliation exists. Demo references are generated locally and are not bank, gateway, or settlement IDs. Admin COD collection is auditable but manual. Before a real provider is added, define provider-specific idempotency, signature verification, webhook replay protection, authorization/capture/refund policy, refund-aware inventory and reward reversals, reconciliation, monitoring, and jurisdiction-specific compliance. PostgreSQL concurrency, production operations, and browser E2E require separate verification.
