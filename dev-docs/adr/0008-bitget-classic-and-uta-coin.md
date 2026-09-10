# ADR 0008: Coexisting Classic and UTA Bitget coin perpetuals

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; UTA support deferred by [ADR 0010](0010-defer-bitget-uta-coin.md)
2. Date: 2026-09-10
3. Amends: [ADR 0005](0005-bitget-product-identities.md)

## Context

The Classic coin listing omits ten existing Catalogue instruments. All ten are
online in the UTA listing under native `*_CM` IDs. Classic and UTA coexist, and
Bitget has scheduled the remaining nine Classic coin perpetuals for retirement on
September 17, 2026. Treating UTA symbols as merely web aliases loses that identity.

## Decision

1. Expose Classic coin perpetuals as `coin-classic`, using native symbols such as
   `BTCUSD`. Expose UTA coin perpetuals as `coin`, using `BTCUSD_CM` unchanged.
2. Keep discovery, caches, books, tickers, candles and funding scoped to the selected
   API family. Do not substitute UTA data for a Classic contract or vice versa.
3. Preserve both Catalogue identities. After confirmed retirement, mark Classic
   entries delisted; do not turn their historical IDs into UTA IDs.
4. Keep UTA coin support public-data only. No account-mode migration, trading,
   private account support, merge or publication is authorized by this decision.
5. Keep `spot`, `usdt` and `usdc` unchanged. This decision does not create duplicate
   UTA exchanges for product lines whose market identity has not been investigated.

## Consequences and remaining qualification

The Catalogue PR restores 19 UTA native IDs and separately records the nine
currently verified Classic listings. Classic trading-page URLs remain absent until
a route to that exact instrument is verified, rather than pointing to UTA.

The public UTA instrument response currently fails Typed validation on delivery
rows whose `fundInterval` is empty. Perpetual validation must stay strict while
delivery contracts are excluded from SDK discovery after typed validation.

UTA coin order quantities are denominated in quote currency, unlike the SDK's
fixed base-unit quantity rules. This ADR does not choose a new `Rules` contract or
authorize substituting USD quantities for base quantities. That decision remains
open; UTA is not release-qualified until it is resolved and tested.

## Alternatives considered

1. Replace Classic with UTA under one ID: discards the distinct identity of existing
   data while both markets coexist.
2. Name UTA `coin-uta`: valid but leaves the long-lived exchange carrying a migration
   suffix after Classic retires; the user chose `coin` for UTA instead.

## References

1. [Classic retirement](https://www.bitget.com/support/articles/12560603893788)
2. [UTA instruments](https://www.bitget.com/docs/catalog/market-market-data/market-instruments)
3. [UTA order quantity units](https://www.bitget.com/docs/catalog/trading/order-management)
4. [Inverse coin contracts](https://www.bitget.com/support/articles/12560603848198)
