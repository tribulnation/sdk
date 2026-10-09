# tribulnation-dydx 0.15.0

Requires SDK >=2.17.0, typed-dydx >=3.7.0 and typed-core >=0.11.0. Full-node fills
report no time instead of the local receive time. See ADR 0044 and "Fill sources" in
the dYdX docs.

Behaviour changes:

1. Node trades (`trades_source` `'node'`, and node-first fills under `'fastest'`) have
   `time=None`: the stream carries block heights, not block times, and waiting for the
   block time would delay the fill. `details['height']` is the fill's block height,
   from which the block time can be resolved later; `trades_history` fills carry it.
   The receive time made fill-to-receive latency read as about zero and disagreed with
   indexer fills, which keep their block time.

`OrderResponse.filled_qty` is `None`: the broadcast answers before the order is
matched in a block. Every other method is unchanged.

Verified by unit fixtures only; the node stream was not run against a full node after
this change.

The SDK floor rises to 2.17.0, whose `Trade.time` is `datetime | None`. Upgrade the
SDK and this adapter together.
