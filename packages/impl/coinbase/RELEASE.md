# tribulnation-coinbase 0.3.0 release candidate

Spot only: INTX perpetuals are dropped. Client order IDs and order IDs on fills.

- **Breaking:** the `intx` exchange, `PerpExchange` and `PerpMarket` are removed. Coinbase retires INTX perpetuals on the Advanced Trade API on 2026-10-01 and moves them to a Deribit-powered gateway (ADR 0031; support tracked in #118). `exchange('intx')` raises `ValueError`, and `perp_exchange()` raises `NotImplementedError`.
- `fees()` is declared unsupported: spot fees always raised, and only INTX served them.
- `place_order` sends `Order['client_order_id']` unchanged as `client_order_id`; with none, the SDK sends a fresh UUID, which Coinbase requires. Reusing an ID returns the order already placed under it. `random_client_order_id()` returns a UUID.
- Fills report `Trade.order_id` from history and streams, and `Trade.client_order_id` from streams.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Client order IDs and order IDs on fills are covered by unit fixtures; no live trading round trip is recorded.
