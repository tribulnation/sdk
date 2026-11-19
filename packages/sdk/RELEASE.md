# tribulnation-sdk 4.2.0

A minor release: the venue's estimated liquidation price on `PerpPosition`, and
`remaining_position_limit` shared by default. Nothing is removed; upgrade the adapters
released with it together (see the end of these notes).

New:

1. `PerpPosition.liquidation_price: Decimal | None`: the venue's estimated liquidation
   price, passed through; `None` when flat, when the venue names none, or where the
   adapter does not read one. The SDK never derives one from margins
   ([ADR 0068](../../dev-docs/adr/0068-perp-position-liquidation-price.md)). It is
   optional on the gateway wire (still `tribulnation-gateway.v2`): an older gateway's
   reply decodes as `None` and an older client ignores it.
2. `POSITION_LIMIT_TTL` (30 s) in `tribulnation.sdk.market`.

Behaviour changes:

1. `remaining_position_limit` (on `MarginMarket`, `PerpExchange`, `TradingVenue`,
   `TradingMarkets` and the gateway proxy) defaults `ttl` to `POSITION_LIMIT_TTL`
   instead of `None`: its answers may be up to 30 s old unless `ttl=None` is passed
   ([ADR 0069](../../dev-docs/adr/0069-position-limits-shared-by-default.md)). Every
   other read keeps ADR 0054's `None` default.

Behaviour changes in the adapters released with this version (see each package's
notes):

1. `perp_position()` fills `liquidation_price` on Aster, GRVT, Hyperliquid and Lighter.
2. `remaining_position_limit()` on Aster, Extended, GRVT, Hyperliquid, Lighter, Nado and
   RISEx answers every market of an account from account-wide or all-market reads shared
   for `ttl`, so a round over many markets costs a few requests, not a few per market.
   Aster shares its per-symbol open-interest allowance for 15 minutes and paces those
   requests; Hyperliquid bounds a flat coin at its `maxLeverage`.

This release goes with tribulnation-aster 0.16.0, -extended 0.5.0, -grvt 0.5.0,
-hyperliquid 0.22.0, -lighter 0.15.0, -nado 0.2.0 and -risex 0.2.0, which require SDK
>=4.2.0. The other adapters keep their current releases and floors; the venue extras
also rise to the releases published since 4.1.0 (bitget 0.14.1, bybit 0.10.1, dydx
0.22.0, ethereum 0.6.1, kraken 0.9.1).
