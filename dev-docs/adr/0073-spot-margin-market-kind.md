# ADR 0073: Spot margin is a market kind, with borrow interest as its carry

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends [0051](0051-spot-perp-market-types-collateral-ids.md)
   (decision 2's `kind`, decision 1's exchange split) and
   [0056](0056-market-kind-aware-support.md) (a third contract kind); implemented for
   Bitget, not release-verified
2. Date: 2026-11-21

## Context

ADR 0051 split markets into `SpotMarket` and `MarginMarket`, with
`PerpMarket(MarginMarket)`, but named only two kinds: `kind` was `'spot' | 'perp'`, and
exchanges split into `SpotExchange` and `PerpExchange`. Bitget's UTA cross spot margin
(`bitget:margin:LITUSDT`, SDK PR #398) is a `MarginMarket` that is not a perpetual, so:

1. `ExchangeDescription.type` could not describe its exchange, and Bitget left `margin`
   out of `exchanges()`. Consumers that enumerate exchanges (the strats P&L report)
   special-cased the venue (`MARGIN_VENUES = {'bitget'}`).
2. `Market.kind` raised on it, and the gateway reported its exchange as `spot`
   (`'perp' if is_perp(exchange) else 'spot'`), so a proxied margin market lost its
   margin reads.
3. A margin short pays borrow interest, its carry, as a perpetual pays funding; there was
   no SDK read for it.

## Decision

1. **Kind.** `MarketKind = Literal['spot', 'margin', 'perp']`. `MarginMarket.kind` is
   `'margin'` (typed `Literal['margin', 'perp']`); `PerpMarket` still answers `'perp'`.
   `ExchangeDescription.type` is `MarketKind`, and consumers skip kinds they do not know.
2. **Exchanges.** `MarginExchange(Exchange)` (kind `'margin'`, `market() -> MarginMarket`)
   carries the margin reads that were on `PerpExchange` (`position`, `leverage`,
   `set_leverage`, `collateral_id`, `available_notional`, `remaining_position_limit`,
   `collateral`), and `PerpExchange` derives from it. `is_margin` narrows exchanges too;
   it stays true for perpetuals, which trade on margin, so `kind == 'margin'` is what
   tells a spot-margin market apart.
3. **Routing.** `margin_exchange()` and `margin_market()` on the root and venue resolve
   margin or perpetual exchanges and markets. The root and venue margin reads (`position`,
   `leverage`, `set_leverage`, `collateral_id`, `available_notional`,
   `remaining_position_limit`) and a pool collateral ID resolve through them instead of
   `perp_market`, so they serve both kinds; perpetual-only reads keep `perp_market`.
4. **Interest.** `MarginMarket.interest_payments(start, end) ->
   PaginatedResponse[InterestPayment]`, with `InterestPayment(time, asset, amount)`:
   the interest on the base asset the market borrows, in that asset's units, negative
   when paid. Quote or collateral debt is pool-wide on unified accounts, so it is not a
   market's: `MarginExchange.interest_payments(None, start, end)` lists every asset.
   The root and venue route `interest_payments(market_id, start, end)`. The default
   raises `NotImplementedError`, like exchange-wide funding. A charge is on an asset,
   not a market, so where several markets borrow one asset from a shared pool the
   implementation reports each charge on one of them only: a sum over markets counts
   it once. Where the venue adds interest to the debt, `position()` includes it, so
   consumers add interest to fill-based P&L, not to a mark-to-market of the position.
5. **Gateway.** `ExchangeResp.type` gains `margin`, sent only for exchanges earlier
   gateways misreported as `spot`; proxies build `ProxyMarginExchange` and
   `ProxyMarginMarket`, which use the existing margin messages. `interest_payments` would
   be a new message kind, a protocol version change, so it is not carried; proxies raise
   `NotImplementedError`. The protocol stays `tribulnation-gateway.v2`.
6. **Contract kinds.** `sdk-dev`'s contract and `impl.toml` kinds add `margin`: a
   method of kind `margin` (`interest_payments`) is documented only for venues listing it
   in `kinds`, so `full`-support perpetual venues do not claim it.
7. **Bitget.** `exchanges()` lists `{'id': 'margin', 'type': 'margin'}`; its `markets()`
   are the public `MARGIN` instrument catalogue. Interest is the UTA ledger's
   `INTEREST_SETTLEMENT_OUT` rows (`/api/v3/account/financial-records`), read under every
   category and deduplicated by ID, since the venue does not say which category books
   pool-wide interest. Of a coin's margin pairs (27 coins have several, e.g. `LINKUSDT`
   and `LINKUSDC`), the USDT-quoted one, else the first symbol, reports them.
8. **Positions on one pool.** A margin pair's `position()` is the pool's net holding of
   its base coin, and every margin pair of the coin reads it: a strategy on any of them
   sizes from it, so zeroing all but one would make the others trade blind. Like spot
   balances across the pairs of one base, it is counted once per account and asset
   (`Market.delta` says so). The `spot` markets on a UTA read only what the pool owns,
   so a borrowed-and-sold short is not repeated on spot.

## Alternatives considered

1. A separate `SpotMarginMarket(MarginMarket)` class for the kind. Rejected: it adds a
   type with no methods of its own; `MarginMarket` already is the type.
2. Keep `kind` two-valued and list margin as `spot` or `perp`. Rejected: either answer
   sends consumers to the wrong reads, which is what the gateway did.
3. Interest in quote units, like funding. Rejected: the venue charges the borrowed asset,
   and a conversion would need a price the SDK does not own; consumers convert.
4. Bumping the gateway protocol to carry `interest_payments` now. Deferred: a version
   change forces the gateway and every client to upgrade together, and no gateway client
   reads interest yet.

## Consequences

1. Existing spot and perpetual consumers keep working: `PerpExchange` and `PerpMarket`
   keep every method, `kind` values for them are unchanged, and the routing change only
   widens which markets the margin reads accept. Code that exhaustively matches
   `MarketKind` or `ExchangeDescription.type` must handle `margin`.
2. A v2 client older than this change fails to decode an `exchange` reply naming
   `margin`, where it used to misread the exchange as spot.
3. Venue adapters adopting it need the release of `tribulnation-sdk` that ships these
   types; Bitget's floor rises with it.
4. Bitget's interest rows are typed from the venue's enumeration and not verified live.
   On 2026-11-21 a 548.22 LIT margin short's debt grew by the first hour's interest at
   borrow (09:57) and by 0.0237 LIT at 11:00, yet the ledger showed no row of any type in
   any category: Bitget may book `INTEREST_SETTLEMENT_OUT` later (daily, or on repayment)
   or not at all. Until a row is seen, `interest_payments` may answer empty while
   interest accrues into the debt; the debt itself (`account/assets`) is then the only
   record.
