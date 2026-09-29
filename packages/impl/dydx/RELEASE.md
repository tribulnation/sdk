# tribulnation-dydx 0.10.0 release candidate

Order IDs on streamed fills.

- Streamed fills report `Trade.order_id` in the SDK's order ID form. dYdX has no free-form client order ID (its client ID is part of the SDK order ID), so `Order['client_order_id']` is ignored, `random_client_order_id()` returns `None`, and `Trade.client_order_id` is `None`.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id`, `Trade.client_order_id` and `Order['client_order_id']`, ADR 0029).

Order IDs on fills are covered by unit fixtures.
