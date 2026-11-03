# tribulnation-aster 0.14.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)) and typed-aster >=0.7.0, unchanged. Upgrade the SDK and this adapter together: this adapter does not work with SDK 3.

Breaking and behaviour changes:

1. `cancel_orders` returns, per order, the acknowledgement or its error: `OrderNotFound` for a gone order (`-2011`, `-2013`), else an `ApiError` subclass. It used to return the raw venue entries.
2. `cancel_order` of a gone order raises `OrderNotFound`. It used to raise `BadRequest`, which `OrderNotFound` is not.
3. `replace_order(s)` use the SDK default: cancel, then place.

Every other method is unchanged.
