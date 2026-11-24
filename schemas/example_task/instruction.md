## Problem Statement
Add percentage and fixed-amount voucher support to checkout cart calculation so eligible line items receive validated discounts.

## Acceptance Criteria
1. Valid active voucher codes reduce the subtotal of eligible items without producing a negative total.
2. Expired or unknown voucher codes raise `InvalidVoucherError` with a descriptive message.
3. Minimum order thresholds are enforced before applying a voucher.
4. Existing checkout calculations without a voucher remain unchanged.

## Interface Contract
- **Module:** `shop/pricing.py`
- **Exception:** `class InvalidVoucherError(ValueError)`
- **Function:** `apply_voucher(cart: Cart, code: str, now: datetime | None = None) -> PricingResult`
- **Return fields:** `PricingResult(subtotal: Decimal, discount: Decimal, total: Decimal, applied_code: str | None)`

## Non-Goals & Constraints
- Do not add external database migrations or network calls.
- Do not modify existing test files.
