# tribulnation-lighter 0.2.0 release candidate

Order IDs on fills.

- Fills from history and streams report `Trade.order_id`: the client order index of
  the account's side, which is the SDK's order ID on Lighter. An order placed outside
  the SDK (index 0) reports `None`.
- `Order['client_order_id']` is ignored, since Lighter's only client-chosen field is
  that order index, and `random_client_order_id()` returns `None`.
  `Trade.client_order_id` is always `None`.

Requires tribulnation-sdk >=2.7.0 (`Trade.order_id` and `Trade.client_order_id`,
ADR 0029) and typed-lighter >=0.2.0.

Public reads are qualified on mainnet; account and trading methods are verified on
testnet. Order IDs on fills are covered by unit fixtures; no live trading round trip
is recorded.
