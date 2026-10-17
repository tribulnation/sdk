# ADR 0046: dYdX order expiry from a cached chain tip

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, unit-tested with fake chains; not live-verified with
   orders; not release-verified.
2. Date: 2026-10-17

## Context

Every dYdX order needs an expiry relative to the chain tip: a good-til-block for
short-term orders, a good-til-block-time for stateful ones. `with_expiry` read the tip
with a `get_latest_block` gRPC call per order (and, without `short_term_gtb` or
`long_term_gtbt`, `typed_dydx` made the same call itself). On the production gateway
this was about 14% of its CPU, mostly decoding the full block, plus one round trip
before every order. dYdX mainnet blocks come about 0.5-0.8 s apart.

## Decision

1. Each client keeps one `ChainTip`: a background poll of CometBFT `/status` (height
   and block time, a small response), every 0.2 s, started by the first order, stopped
   after 30 s without one (the next order restarts it) and cancelled when the client
   exits. It reads the account's full node when
   `full_node_grpc` and `full_node_rpc` are set, else the public chain endpoint. A node
   reporting `catching_up` is not cached. Poll failures are logged once per outage and
   retried with backoff up to 5 s; they never reach order placement.
2. The tip is never extrapolated. Cached heights only move forward, so an expiry built
   from the cache is never later than one built from a live read of the same node.
3. A cached tip is used only while young enough for the order to still be alive when it
   reaches the chain: at most `block_max_age` (2 s, an `Exchange.new` argument), and for
   short-term orders at most `(short_term_gtb - 1) * 0.4` s, 0.4 s being a lower bound
   on the block interval. Otherwise, or with no tip yet, the order reads the tip live
   with `get_latest_block` from the same node, which also refreshes the cache.
4. The SDK always sets the expiry itself. `short_term_gtb` defaults to, and is capped
   at, 18 blocks: the 20-block `ShortBlockWindow` less 2 for a tip node running ahead of
   the node that checks the order. `long_term_gtbt` defaults to, and is capped at, the
   95-day `StatefulOrderTimeWindow` less 60 s.

## Consequences

1. Orders whose tip is fresh make no request before broadcasting. With the 0.2 s poll
   and a nearby node, that is every order with `short_term_gtb >= 2`.
2. Short-term orders without `short_term_gtb` now expire 18 blocks past the tip, not 20;
   larger values are capped at 18 rather than rejected by the chain.
3. While it places orders, each client polls its node 5 times a second, about 1.5 ms of
   CPU per poll over TLS to the public endpoint; a per-order `get_latest_block` cost
   about 3 ms. The poll pays off from about 2.5 orders a second and costs nothing idle.
4. Cancellations still let `typed_dydx` read the tip per call; reusing the cached tip
   for them is left open, since a cancel must not expire before the order it cancels.
