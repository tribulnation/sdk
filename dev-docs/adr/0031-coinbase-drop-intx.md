# ADR 0031: Drop Coinbase INTX perpetuals

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; unit fixtures verify the spot-only surface.
2. Date: 2026-09-29

## Context

`tribulnation-coinbase` served INTX perpetuals as the `intx` exchange through the
Advanced Trade API. Coinbase deprecates those endpoints: "retires October 1, 2026.
International derivatives trading is moving to the new Deribit-powered gateway"
([Coinbase docs](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/perpetual)).
The cutover has no parallel-running window.

Two days before it, the qualification key already sees no INTX products: the
authenticated catalogue lists none and `BTC-PERP-INTX` returns `404 Product
BTC-PERP-INTX not supported`, while the public catalogue still lists 131
([#115](https://github.com/tribulnation/sdk/issues/115)). Coinbase surfaces and
consistency therefore fail on every INTX check, which blocks every release gated on
all-venue evidence.

## Decision

1. Drop the `intx` exchange. `CoinbaseMarket.exchanges()` lists only `spot`;
   `exchange('intx')` raises `ValueError`, and `perp_exchange()` keeps the base
   class's `NotImplementedError`.
2. Remove `PerpExchange`, `PerpMarket` and their INTX-only helpers: funding state and
   history, INTX portfolio position and collateral, perpetual catalogue filtering and
   the INTX fee tier. `fees()` was supported only for INTX, so it is now unsupported.
3. `impl.toml`, the method reference and the qualification reference cases describe
   spot only.

Spot is unchanged.

## Alternatives considered

- Keep INTX until the cutover: it already fails qualification, and the endpoints stop
  serving it two days later.
- Support the new gateway now: it is Deribit's JSON-RPC API at `drb.coinbase.com`,
  with Deribit-style IDs such as `BTC_USDC-PERPETUAL` and CDP-key authentication. It
  is a separate feature, probably built on the existing Deribit client, tracked in
  [#118](https://github.com/tribulnation/sdk/issues/118).

## Consequences

Removing `PerpExchange` and `PerpMarket` breaks imports of them, so the next
`tribulnation-coinbase` release is a minor bump (0.2.x to 0.3.0). The Coinbase
reference candle case in `sdk-dev` is removed, and since `sdk-dev` is part of every
venue's evidence fingerprint, all venues must be re-recorded after this change.
