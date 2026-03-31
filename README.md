# Trading SDK

> An abstract, fully-typed, async Python SDK for automated crypto trading.

## Quick Start

```python
from trading_sdk import TradingSDK

sdk = TradingSDK()
mexc = await sdk.market('mexc:spot:BTCUSDT')
dydx = await sdk.market('dydx:perp:BTC-USD')

async for my_trade in mexc.trades_stream():
  print(f'Hedging {my_trade}')
  await dydx.place_order({
    'type': 'LIMIT',
    'qty': -my_trade.qty,
    'price': my_trade.price,
  })
```

## Installation

```bash
pip install trading-sdk[mexc, dydx, hyperliquid]
```

## Supported Venues

- `mexc`: [MEXC](https://www.mexc.com/)
- `dydx`: [dYdX](https://dydx.exchange/)
- `hyperliquid`: [Hyperliquid](https://hyperliquid.xyz/)

## Market IDs

Market IDs have this form: `<venue_id>:<exchange_id>:<market_id>`.

You can also scope. These are equivalent:

1. Directly on the SDK:

  ```python
  await sdk.book('mexc:spot:BTCUSDT')
  ```

2. By venue:

  ```python
  venue = await sdk.venue('mexc')
  await venue.book('spot:BTCUSDT')
  ```

3. By exchange:

  ```python
  exchange = await venue.exchange('spot')
  await exchange.book('BTCUSDT')
  ```

4. By market:

  ```python
  market = await exchange.market('BTCUSDT')
  await market.depth()
  ```

## Market Interface

- Public data:
  - `depth() -> Book`: order book
  - `depth_stream() -> Stream[Book]`: real-time order book updates
  - `rules() -> Rules`: market rules (tick size, fees, etc.)
- User data:
  - `query_order(id: str) -> OrderState | None`
  - `open_orders() -> Sequence[OrderState]`
  - `trades_history(start: datetime, end: datetime) -> AsyncIterable[Sequence[Trade]]`
  - `trades_stream() -> Stream[Trade]`: real-time user trades
  - `position() -> Position`: base-asset position	
- Trading:
  - `place_order(order: Order) -> OrderResponse`
  - `place_orders(orders: Sequence[Order]) -> Sequence[OrderResponse]`
  - `cancel_order(id: str) -> Any`
  - `cancel_orders(ids: Sequence[str])`
  - `cancel_open_orders()`
- Perpetual markets:
  - `index() -> Decimal`: index price
  - `next_funding() -> FundingRate`: next funding rate
  - `funding_history(start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingRate]]`: market funding rate history
  - `funding_payments(start: datetime, end: datetime) -> AsyncIterable[Sequence[FundingPayment]]`: your funding payments history
  - `position() -> PerpPosition`: open base-asset position, including the entry price