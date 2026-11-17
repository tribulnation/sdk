# tribulnation-grvt 0.3.0

Requires SDK >=4.0.0 (`place_orders` results per order, `replace_order(s)` and `OrderNotFound`, [ADR 0059](../../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)), typed-grvt >=0.2.0 and typed-core >=0.13, unchanged. `replace_order(s)` use the SDK default (cancel, then place); GRVT cancels asynchronously, so a cancel of a gone order is not reported as `OrderNotFound`.

New:

1. A `spot` exchange of GRVT's `SPOT_SWAP` instruments (`GRVT_USDT_SpotSwap`, `USDC_USDT_SpotSwap`): ordinary order books traded with the perpetuals' endpoints and settled in the trading sub-account's spot wallet, separate from its futures wallet. Spot markets are SDK `SpotMarket`s sharing the perpetuals' book, candle, order, cancellation and fill paths.
2. Spot `balances()`/`balance()` read the spot account summary: `total` is the balance, `free` is `available_to_transfer`. On testnet, resting `POST_ONLY` orders hold their quote cost (buys) or base quantity (sells) there, and cancellations release it.
3. Spot `collateral_ids()` are `<account>:spot:<asset>` ([ADR 0051](../../../dev-docs/adr/0051-spot-perp-market-types-collateral-ids.md)).
4. Spot `rules()` have no `fee_asset` and no fees (GRVT publishes no standard spot schedule); `fees()` reads the account tier's spot rates. Fills pay fees in the delivered asset.
5. Account filters (open orders, trades, fills) carry the instrument's kind, since `GRVT_USDT_SpotSwap` shares base and quote with `GRVT_USDT_Perp`.

Spot trading was verified on testnet (`POST_ONLY` and `MARKET` buys and sells, the three cancellation methods, the fills stream and trade history); no spot order was placed on mainnet.

Every other method is unchanged.

Release qualification on 2026-11-04 passed the read suites and market consistency.
Committed evidence under `release-evidence/grvt/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.
