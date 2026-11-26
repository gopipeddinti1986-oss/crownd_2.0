# Referral attribution and conversion rules

CROWND reuses its existing `Referral` and accepted `Application` records. A creator may generate campaign links only while the creator, brand, campaign, dates, participation, campaign products, and link are eligible. A product-specific destination is optional and is validated by the backend against campaign eligibility. Clicks are engagement events; they do not themselves create conversions or rewards.

## Attribution

- `/r/{code}` validates eligibility before recording a click or updating attribution. A signed, HttpOnly, SameSite visitor cookie carries an opaque random token; the server stores its SHA-256 hash and first/last referral IDs, touch times, expiry, and (after checkout) customer association. The legacy signed referral cookie remains supported for already-issued links.
- Attribution is **last valid referral** for the configured attribution window (seven days by default): each new eligible referral replaces last touch and refreshes expiry. First touch is retained for analysis/history. Direct traffic, product browsing, cart changes, and invalid referrals do not erase or replace the last valid referral.
- Checkout takes attribution only from the signed server-side cookie state. It ignores any frontend-provided creator, campaign, referral, or conversion status. Eligibility and product ownership/status are rechecked server-side when order items are created.
- Mixed carts can contain eligible and ineligible products. Only eligible order lines receive the referral ID and contribute their line amount to the conversion/reward basis; the order's referral ID remains a compatibility summary. Campaigns without an explicit product list use their active brand products.

## Conversion/payment lifecycle

- A conversion is an order-backed ledger record, unique per order, created transactionally with checkout. A product view, cart addition, click, or order record alone is not a confirmed conversion.
- Successful local Demo Payment simulation confirms a conversion marked `is_demo`; it is not a real online payment. Failed demo payment cancels the conversion and restores stock.
- COD creates a pending conversion while payment remains unpaid. Only the authorized admin collection action after delivery confirms the conversion and creates its reward. A normal eligible unpaid-order cancellation transitions the conversion to `cancelled` without deleting its event history or creating a reward.
- Self-referrals are ineligible, have zero attributed reward basis, and receive an explainable risk flag. Repeated-customer patterns are review-only flags; flags do not auto-ban users or automatically disqualify other orders.
- Rewards are created once from the confirmed conversion's attributed item amount. Demo rewards stay explicitly simulated/non-payable under the existing payout rules.

## Analytics, privacy, and known limits

Creator, brand, and admin APIs/UI report link clicks, distinct non-empty visitor hashes, product-view/cart-add activity, order/conversion statuses, and demo/COD counts. Creator and brand conversion views omit customer contact/shipping data; risk responses do not expose customer IDs or visitor hashes. The system does not persist raw IP addresses or full user-agent strings; it retains only a hash of a random token, sanitized referrer host, and coarse device category.

SQLite fresh-upgrade and downgrade/re-upgrade have been verified. PostgreSQL migrations, multi-worker race/load behavior, browser E2E, production consent/retention/legal review, and external payment/refund provider workflows are not verified or implemented. Paid orders cannot use the ordinary cancellation path; a full paid-order refund/reversal workflow remains future work. The referral click endpoint still returns destination metadata for the current SPA rather than delivering a full server redirect. Product views/cart additions are recorded only when the signed attribution cookie exists and the product/link is still eligible; they remain engagement metrics, not conversions.
