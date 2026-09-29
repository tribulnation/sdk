# tribulnation-sdk 2.7.0 release candidate

Client order IDs on orders, and order IDs on fills.

- `Order` takes an optional `client_order_id` (`str | None`, where `None` is the same as
  leaving it out). Venues with native client order IDs send it unchanged; the rest
  ignore it.
- `Market.random_client_order_id()` generates a fresh ID in the form that market's
  `place_order` sends, or returns `None` where the market ignores the IDs.
- `Trade` (and so `ExchangeTrade`) gains `order_id` and `client_order_id`, both
  defaulting to `None` where the venue does not report them.

Existing `Order`, `Trade` and `Market` code keeps working. Implementations reporting the
new fields need this version, so their floors rise when they are released. See
[ADR 0029](../../dev-docs/adr/0029-client-order-ids.md) and
[Client Order IDs](../../docs/market/client-order-ids.md).

Publication requires fresh all-venue read-suite and applicable Market consistency
evidence against the pinned Catalogue snapshot.
