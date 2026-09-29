# tribulnation-bitget 0.9.0 release candidate

Order and client order IDs on fills.

- Fills report `Trade.order_id` from history and streams. `Trade.client_order_id` comes from UTA history and streams, and from Classic futures streams.
- The Bitget implementation does not trade, so `random_client_order_id()` returns `None`.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Order IDs on fills are covered by unit fixtures.
