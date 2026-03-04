# Market Interface

## Overview

`Market` is the core trading interface. It is composed of three modules:

- `market.data`: market data (rules, order book, and perp-specific funding/index).
- `market.trade`: order placement and cancellation.
- `market.user`: balances, positions, orders, trades, and perp funding payments.

Perpetual markets use `PerpMarket`, which extends `Market` with funding and index data and funding payment history.

## Core Types

`Market`
- Properties: `venue`, `market_id`, `id` (computed as `{venue}:{market_id}`)
- Modules: `data`, `trade`, `user`

`PerpMarket`
- Same as `Market`, plus perp data and user funding modules (see below)

## Market Data (`market.data`)

`Rules.get() -> Rules.Rules`
- Returns market rules such as tick sizes, step sizes, fee rates, and min/max constraints.
- Helper methods on `Rules.Rules`: `min_price(mark_price)`, `max_price(mark_price)`, `min_qty(price)`, `trunc_qty(base_qty, price)`, `round_price(price)`, `amount2qty(quote_amount, price)`, `qty2amount(base_qty, price)`.

`Depth.book(limit: int | None = None) -> Book`
- Returns an order book with `bids`, `asks`, and convenience helpers like `best_bid`, `best_ask`, and price/size utilities.

Perp-only data:
- `Funding.history(start, end)` and `Funding.next()`
- `Index.price()`

## Trading (`market.trade`)

`Place.order(order: Place.Order) -> Place.Result`
- Order fields: `qty` (signed base quantity), `price` (quote price), `type` (`LIMIT` or `POST_ONLY`).

`Place.orders(orders: Sequence[Place.Order]) -> Sequence[Place.Result]`

`Cancel.order(id: str) -> Cancel.Result`

`Cancel.orders(ids: Sequence[str])`

`Cancel.open()`
- Cancels all open orders.

## User Data (`market.user`)

`Balances.quote() -> Balances.Balance`
- Quote/collateral balance with `free`, `locked`, and `total`.

`Position.get() -> Position.Position`
- Base asset position size.

Perp-only position:
- `PerpPosition.get()` includes `entry_price`.

`Trades.history(start, end) -> AsyncIterable[Sequence[Trades.Trade]]`
- Trade includes `id`, `price`, `qty`, `time`, `maker`, and optional `fee`.

`Trades.stream() -> AsyncIterable[Trades.Trade]`

`Orders.query(id) -> Orders.Order`

`Orders.open() -> Sequence[Orders.Order]`

Perp-only user funding payments:
- `Funding.history(start, end) -> AsyncIterable[Sequence[Funding.Payment]]`

## Related

- `sdk/src/trading_sdk/market/`
- `trading_sdk.impl.market.load_market()` helper in `sdk/src/trading_sdk/impl/market.py`
