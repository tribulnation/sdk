# Trading SDK

> A fully-typed, async Python SDK for automated crypto trading.

## Installation

```bash
pip install trading-sdk
pip install mexc-trading-sdk # or others, see below
```

## Features

- **Fully async**
- **Type-annotated**: with `TypedDict`, `Literal`, etc.
- **Composable** : cherry-pick the exact methods you need.

## Installation

```bash
pip install trading-sdk
```

## Usage

1. Define your strategy using the available interfaces (or a composition of them).

```python
from trading_sdk.spot import Trading, MarketData

class MyClient(Trading, MarketData):
  ...

async def micro_strategy(client: MyClient):
  while True:
    book = await client.depth('BTCUSDT', '15m')
    await client.place_order('BTCUSDT', {
      'quantity': '1',
      'type': 'MARKET',
      'side': 'BUY',
    })
    await asyncio.sleep(3600*24)
```

2. Use an existing exchange implementation.

```python
from mexc.sdk import MEXC

async with MEXC(API_KEY, API_SECRET) as client:
  await micro_strategy(client)
```

3. Or implement your own.

```python
from trading_sdk.spot import Trading, MarketData

class MyClient(Trading, MarketData):
  async def depth(self, symbol: str, interval: str) -> dict:
    ...

  async def place_order(self, symbol: str, order: dict) -> dict:
    ...

  # ...
```
