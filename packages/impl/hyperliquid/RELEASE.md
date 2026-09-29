# tribulnation-hyperliquid 0.10.0 release candidate

Client order IDs (cloids) and order IDs on fills.

- `place_order` sends `Order['client_order_id']` unchanged as the order's `cloid` (`0x` and 32 hex digits). `random_client_order_id()` generates one.
- Fills from history, streams and exchange-wide history report `Trade.order_id` and `Trade.client_order_id`.
- Requires typed-hyperliquid >=2.3.0, which types `cloid` on fills.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Client order IDs and order IDs on fills are covered by unit fixtures; no live trading round trip is recorded.
