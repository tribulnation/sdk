# Trading SDK

> An abstract, fully-typed, async Python SDK for automated crypto trading.

## Installation

```bash
pip install trading-sdk
pip install mexc-trading-sdk # or others, see below
```

## Features

- **Fully async**
- **Type-annotated**: with `TypedDict`, `Literal`, etc.
- **Composable** : cherry-pick the exact methods you need.

## Supported Exchanges

- [MEXC](https://github.com/tribulnation/mexc)
- [Deribit](https://github.com/tribulnation/deribit) (coming soon)
- [Bybit](https://github.com/tribulnation/bybit) (coming soon)
- [Bitget](https://github.com/tribulnation/bitget) (coming soon)
- [Binance](https://github.com/tribulnation/binance) (coming soon)

## Usage

1. Define your strategy.

```python
from sdk import Market

async def strategy(market: Market):
  while True:
    book = await market.depth(limit=1)
    order_id = await market.place_order({
      'quantity': '1',
      'type': 'LIMIT',
      'side': 'BUY',
      'price': book.asks[0].price,
    })
    await asyncio.sleep(3600*24)
    order = await market.order_state(order_id)
    if order.status != 'FILLED':
      await market.cancel_order(order_id)
```

2. Use an existing exchange implementation (or implement your own).

```python
from mexc.sdk import MEXC

async with MEXC(API_KEY, API_SECRET) as sdk:
  market = sdk.spot('BTC', 'USDT')
  await strategy(market)
```
