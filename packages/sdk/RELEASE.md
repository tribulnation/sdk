# tribulnation-sdk 4.0.0

A breaking release. `place_orders` now returns one result per order, the response or
its error, and markets gain `replace_order(s)` and `OrderNotFound`
([ADR 0059](../../dev-docs/adr/0059-replace-orders-and-order-not-found.md)). Upgrade the
adapters released with it together; see the end of these notes.

Breaking changes:

1. **`place_orders` returns `Sequence[OrderResponse | Exception]`** (ADR 0059). One
   entry per order, in order: the `OrderResponse`, or the exception that order raised.
   A refused order no longer hides the response of one that rests, and `place_orders`
   no longer raises for one order's failure: check each entry
   (`isinstance(result, Exception)`). The default still places the orders in parallel
   through `place_order`; the gateway proxy returns the same shape.
2. **Adapter floors.** The adapters released with this version implement or rely on the
   new base-class methods, so each requires `tribulnation-sdk>=4.0.0`, and the SDK's
   venue extras for them require those releases.

New:

1. `OrderNotFound(ApiError)` in `tribulnation.sdk.core`: the venue answered that the
   order does not exist (filled, cancelled or never placed). `cancel_order` raises it
   only where the venue's answer makes that certain (Hyperliquid, margin.trade, Aster);
   venues with asynchronous cancels (Lighter, GRVT, Extended) cannot tell.
2. `Market.replace_order(id, order, *, settings={}) -> OrderResponse` swaps a resting
   order for a new one and returns the order now resting, whose id may differ. The
   default cancels, then places; a cancel raising `OrderNotFound` still places, any other
   cancel error propagates and nothing is placed.
   `Market.replace_orders(orders, *, settings={})` returns one response or error per
   entry. `Markets`, `Exchange` and `TradingVenue` delegate both. The gateway proxies
   `replace_orders` as one call with an error per entry, and `OrderNotFound` joins the
   wire's exception names.
3. `delta(*, ttl=None)` and `hold(*, qty, price, ttl=None)` defaults on `SpotMarket` and
   `MarginMarket` ([ADR 0058](../../dev-docs/adr/0058-market-delta-and-hold.md)): signed
   base exposure, and the collateral an order would hold. `Market` declares both and
   raises `NotImplementedError` there.
4. `QualifiedExchangeId` and `QualifiedMarketId` in `tribulnation.sdk.market` parse
   account-qualified exchange and market IDs.
5. `Rules.sig_figs: int | None = None`: the most significant figures in a price, integers
   exempt. With it, `price_step(price)` is the coarser of `tick_size` and the last
   significant figure's step; `round_price`, `trunc_price`, `ceil_price` and
   `valid_price` follow it. `None` (the default) rounds as before.

Behaviour changes in the adapters released with this version (see each package's
notes):

1. Hyperliquid and margin.trade set `Rules.sig_figs=5` with a finer `tick_size`, and
   raise `ValueError` on an off-grid order price instead of rounding it. Both replace
   orders with one `batchModify`.
2. Aster and margin.trade `cancel_orders` return exceptions (`OrderNotFound` or an
   `ApiError`) instead of raw venue entries; Aster's `cancel_order` of a gone order
   raises `OrderNotFound` instead of `BadRequest`.
3. margin.trade checks the signing key's master account on entry.
4. Lighter sends waiting order transactions as one `sendTxBatch`
   ([ADR 0057](../../dev-docs/adr/0057-lighter-batched-order-transactions.md)) and can
   modify a resting order with the `replaces` setting.

This release goes with tribulnation-aster 0.14.0, -dydx 0.21.0, -hyperliquid 0.20.0,
-lighter 0.13.0 and -margin-trade 0.3.0, which require SDK >=4.0.0. The other adapters
keep their current releases and SDK 3 floors.
