# tribulnation-mexc 2.2.0 release candidate

Client order IDs on spot, order IDs on fills, and missing index prices.

- Spot `place_order` sends `Order['client_order_id']` unchanged as `newClientOrderId`. `random_client_order_id()` returns 32 random hex digits on spot and `None` on perpetuals.
- Spot fills from history and streams report `Trade.order_id` and `Trade.client_order_id`.
- Perpetual tickers without an index price raise `MissingData` (an `ApiError`) instead of failing validation. A full `perp_stats()` read leaves those contracts out and returns the rest; naming one raises (ADR 0025, amended by ADR 0030).

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Client order IDs and order IDs on fills are covered by unit fixtures; no live trading round trip is recorded.
