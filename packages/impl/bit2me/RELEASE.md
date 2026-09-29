# tribulnation-bit2me 0.7.0 release candidate

Client order IDs and order IDs on fills.

- `place_order` sends `Order['client_order_id']` unchanged as `clientOrderId`; `None` or no key sends none. `random_client_order_id()` returns 32 random hex digits.
- Fills from history and streams report `Trade.order_id` and `Trade.client_order_id`.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Client order IDs and order IDs on fills are covered by unit fixtures; no live trading round trip is recorded.
