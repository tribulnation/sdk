# ADR 0059: `replace_order(s)` and `OrderNotFound`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed
2. Date: 2026-10-31

## Context

A market maker that keeps at most one order per side moves it every cycle. Today it can
only cancel and place, two calls whose combined outcome it has to reason about itself,
and venues with a native modify (Hyperliquid, margin.trade, Aster) or a batched
transaction (Lighter, [ADR 0057](0057-lighter-batched-order-transactions.md)) are only
reachable by calling their typed clients directly, which the engine gateway cannot
proxy.

Replacing safely needs one distinction the SDK does not make: whether a failed cancel
means the order is already gone (filled, cancelled, never placed) or that the outcome is
unknown. Placing after the first is safe; placing after the second can leave two orders
on one side.

Venues answer a cancel of a gone order differently:

1. Hyperliquid: "Order was never placed, already canceled, or filled."
2. margin.trade: status "order not found".
3. Aster: code -2011 on cancel, -2013 on modify and query.
4. Lighter and GRVT: the cancel is accepted and nothing is reported.
5. dYdX: short-term cancels of unknown orders are accepted; long-term ones fail CheckTx.
6. Extended: not yet established.

Native modifies differ too. Hyperliquid's and margin.trade's `batchModify` cancel and
place a new order (new id) per entry, and place nothing when the old order is gone.
Hyperliquid's single `modify` reports no status. Aster keeps the id and takes the total
size, filled part included. Lighter accepts a modify of a gone order and drops it
silently. Extended's replace needs the old order's client id, which the SDK does not
return, and rejects the new order asynchronously when the old one is gone.

## Decision

1. `OrderNotFound(ApiError)` in `tribulnation.sdk.core`: the venue answered that the
   order does not exist (filled, cancelled or never placed). `cancel_order` raises it
   only where the venue's answer makes that certain; where a venue cannot tell, a cancel
   of a gone order returns normally. `cancel_orders` overrides that return per-order
   results report it per order. Hyperliquid, margin.trade and Aster (codes -2011 and
   -2013) raise it; Lighter, GRVT and Extended (asynchronous cancels) cannot tell.
2. `Market.replace_order(id, order, *, settings={}) -> OrderResponse` swaps resting
   order `id` for `order` and returns the order now resting, whose id may differ.
   `order['qty']` is the size to rest from now on: a venue whose modify sets the total
   size adds the filled part itself.
3. The default replace cancels, then places. A cancel raising `OrderNotFound` still
   places; any other cancel error propagates and nothing is placed, so a side never ends
   up with two orders.
4. `Market.replace_orders(orders: Sequence[tuple[str, Order]], *, settings={})
   -> Sequence[OrderResponse | Exception]` returns one result or error per entry, in
   order. The default runs `replace_order` per entry concurrently. `place_orders` and
   `cancel_orders` keep raising their first error.
5. Venue overrides:
   1. Hyperliquid and margin.trade: one `batchModify` per call, without Hyperliquid's
      always-place flag; an entry failing because the old order is gone falls back to a
      plain placement. An entry error saying the old order was cancelled and the new one
      refused is an `OrderRejected`: on Hyperliquid one starting `Error placing new order
      during modify:`, on margin.trade `Canceled due to post only`. Any other entry error is an `ApiError`, since the old order may
      still rest. Without the flag Hyperliquid modifies only into `Alo` orders, so its
      non-`POST_ONLY` entries take the default cancel then place.
   2. Aster, Extended, GRVT, Lighter and dYdX: the default. Aster and margin.trade
      `cancel_orders` report failures as exceptions rather than raw venue entries.
      Lighter's `{'lighter': {'replaces': id}}` modify stays an opt-in on `place_order`.
6. `Rules.sig_figs: int | None = None` gives the most significant figures in a price,
   integers exempt. With it, `price_step(price)` is the coarser of `tick_size` and the
   last significant figure's step, never coarser than 1. `round_price`, `trunc_price` and
   `ceil_price` follow that step, and `valid_price` checks it. Hyperliquid and
   margin.trade set `sig_figs=5`, with `tick_size` the documented finest step,
   `10^-(max decimals - szDecimals)`; the old cap at 5 decimals is gone. Both raise
   `ValueError` before signing on an off-grid price, where they used to round half-up.
   dYdX keeps flooring prices: its live strategies rely on it, and it is outside this
   change.
7. The gateway proxies both methods and carries per-entry errors.
8. Entering a signed margin.trade venue reads the key's master account (`getUser`). A
   configured `address` that is not it raises `AuthError`; an omitted one becomes it.
   Otherwise an agent key with the wrong `address` trades the master and reads another
   account, and `open_orders`, which strategies rely on to avoid stacking quotes,
   comes back empty.

## Alternatives considered

1. A native modify on Lighter: a modify of a gone order is accepted and dropped, so
   `replace_order` would report an order resting when none is, until the caller's next
   read.
2. A Lighter cancel and create in one `sendTxBatch`, kept together by the batcher: one
   request per replace, but the batcher would need groups it never splits. The default
   is used instead; concurrent replaces still share batches through the existing
   batcher.
3. Aster's native modify: it needs the order's filled size, which costs a read per
   replace, and races with fills. The default spends two requests and keeps the contract
   simple; a modify can come later.
4. Hyperliquid's always-place flag: it also places when the cancel failed for another
   reason, which can leave two orders.
5. Extended's `cancelId` replace: needs the client id, and a gone order rejects the new
   one asynchronously instead of placing it.
6. Making `place_orders` and `cancel_orders` return per-entry errors too: a breaking
   change to existing callers, outside this decision.
7. A `Rules` subclass for significant-figure venues: the gateway decodes rules as
   `SpotRules | Rules`, so a subclass would arrive as plain `Rules` and round on the
   wrong grid. Hyperliquid spot rules would also need a second subclass of `SpotRules`.
   An optional field crosses the gateway, and older peers ignore it.

## Consequences

1. A post-only requote costs one request on Hyperliquid and margin.trade, three when the
   old order is gone; two (cancel, place) elsewhere, fewer on Lighter when concurrent
   transactions share a `sendTxBatch`.
2. Venues that cannot report a gone order (Lighter, GRVT, dYdX short-term) still
   satisfy the default: their cancel never blocks the placement.
3. Hyperliquid and margin.trade callers passing off-grid prices now get an error. Rounding
   with the returned `Rules` keeps them on the grid. Their `tick_size` gets finer for
   prices below 0.1: callers using `tick_size` directly, rather than `price_step`, see
   a step finer than the venue accepts at most prices.
4. `scaled()` keeps `sig_figs`. Significant figures don't change under scaling by
   powers of ten, but the integer exemption is in venue units, so for a scaled market
   (`kPEPE`) the cap of 1 is not exact.
5. Released SDK first. Hyperliquid, margin.trade and Aster raise their
   `tribulnation-sdk` floor, since they import `OrderNotFound` and `valid_price`.
6. Verified on the Hyperliquid testnet (2026-10-31, ETH): a `batchModify` of a cancelled
   or filled order answers `Cannot modify canceled or filled order`. A post-only modify
   that would cross, and one under the $10 minimum, answer `Error placing new order
   during modify: ...`, and the old order ends `canceled`.
7. Verified on the margin.trade testnet (2026-10-31, SOL):
   1. A `batchModify` of a cancelled or filled order answers `cancel failed: order not
      found`. A cancel of a gone order answers `order not found`, alone or per order in
      a batch beside a live one.
   2. A post-only modify that would cross answers `Canceled due to post only`, and the
      old order is no longer active.
   3. Unlike Hyperliquid, a modify below $10 was accepted and rested (0.01 SOL), so
      margin.trade's testnet enforces no minimum order value there.
   4. An `orderStatus` read ignores its `user`: it returns any account's order by ID.
   5. A first run read no open orders, fills or position while orders rested and
      filled. The cause was configuration: the configured `address` was the agent
      key's own address, not its master's. The venue routes an agent's actions to its
      master whatever `address` says, while every read went to the agent's empty
      account. With the master's address, `open_orders` lists resting orders at once.
      Decision 8 turns that mistake into an error.
8. Verification still needed against live venues: the tick margin.trade observed on
   PRL/USDC (1e-5, where the documented rule gives 1e-6); Extended's cancel of an
   unknown order; and dYdX's long-term cancel error.
