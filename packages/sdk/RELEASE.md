# tribulnation-sdk 4.3.0

A minor release: spot margin becomes a market kind, with borrow interest as its carry
([ADR 0073](../../dev-docs/adr/0073-spot-margin-market-kind.md)). Nothing is removed;
upgrade tribulnation-bitget 0.15.0, released with it, together (see the end of these
notes).

New:

1. `MarketKind` is `'spot' | 'margin' | 'perp'`. `MarginMarket.kind` answers
   `'margin'` (spot pairs traded on borrowed money); `PerpMarket` still answers
   `'perp'`. `ExchangeDescription.type` is a `MarketKind`, so `exchanges()` can list
   margin exchanges.
2. `MarginExchange` (in `tribulnation.sdk.market`), kind `'margin'`: it carries the
   margin reads that were on `PerpExchange` (`position`, `leverage`, `set_leverage`,
   `collateral_id`, `available_notional`, `remaining_position_limit`, `collateral`),
   and `PerpExchange` now derives from it. `is_margin` also narrows exchanges.
3. `margin_exchange()` and `margin_market()` on the root (`MarketSDK`) and on each
   venue resolve margin or perpetual exchanges and markets, e.g.
   `bitget:margin:LITUSDT`.
4. `MarginMarket.interest_payments(start, end) -> PaginatedResponse[InterestPayment]`
   and `InterestPayment(time, asset, amount)`: the borrow interest on the base asset,
   in that asset's units, negative when paid. `MarginExchange.interest_payments(None,
   start, end)` lists every asset the pool owes; the root and venue route
   `interest_payments(market_id, start, end)`. The default raises
   `NotImplementedError`. A charge is reported by one market of the asset only, and
   where the venue adds interest to the debt, `position()` already includes it: add
   it to fill-based P&L, not to a mark-to-market of the position.

Changed:

1. The root and venue margin reads (`position`, `leverage`, `set_leverage`,
   `collateral_id`, `available_notional`, `remaining_position_limit`) and pool
   collateral IDs resolve through `margin_market()` instead of `perp_market()`, so
   they accept spot-margin markets as well as perpetuals. Perpetual-only reads keep
   `perp_market()`.
2. `is_margin` stays true for perpetuals, which trade on margin; `kind == 'margin'`
   tells a spot-margin market apart. Code matching `MarketKind` or
   `ExchangeDescription.type` exhaustively must handle `'margin'`.
3. `MarginMarket.delta` documents that markets of one asset share a holding (every
   spot pair of a base, every margin pair of a unified pool), so deltas are summed
   once per account and asset, not once per market.

Gateway (still `tribulnation-gateway.v2`):

1. The `exchange` reply's `type` gains `'margin'`, sent only for exchanges earlier
   gateways misreported as `'spot'`. Proxies build `ProxyMarginExchange` and
   `ProxyMarginMarket` over the existing margin messages; `leverage`, `set_leverage`
   and exchange collateral accept margin markets.
2. **Compatibility:** a client older than 4.3.0 fails to decode an `exchange` reply
   naming `margin` (it used to misread the exchange as spot). Upgrade clients before,
   or together with, a gateway serving a venue with margin exchanges (Bitget from
   0.15.0).
3. `interest_payments` is not carried: it would be a new message kind, a protocol
   version change. Proxies raise `NotImplementedError`; read interest with a direct
   SDK.

This release goes with tribulnation-bitget 0.15.0 (its `margin` exchange and
`interest_payments`), which requires SDK >=4.3.0; the `bitget` extra rises to it. The
other adapters keep their current releases and floors.
