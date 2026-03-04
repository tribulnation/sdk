# Trading SDK

> An abstract, fully-typed, async Python SDK for automated crypto trading, with exchange-specific implementations.

**Status: Beta.** The API is under active development and **very likely to change at any time**.

## Installation

```bash
pip install trading-sdk
pip install mexc-trading-sdk  # or any exchange package listed below
```

## Features

- **Fully async**
- **Type-annotated**: `TypedDict`, `Literal`, `Protocol`, etc.
- **Composable**: mix and match market data, trading, user data, wallet, earn, and reporting modules.
- **Exchange-agnostic core** with per-exchange adapters under `impl/`.

## Quickstart

1. Define your strategy against the abstract `Market` interface.

```python
from trading_sdk import Market

async def strategy(market: Market):
  book = await market.data.depth(limit=1)
  best_ask = book.best_ask.price
  result = await market.trade.place.order({
    "qty": "1",
    "price": str(best_ask),
    "type": "LIMIT",
  })

  order = await market.user.orders.query(result.id)
  if order.active:
    await market.trade.cancel.order(result.id)
```

2. Use an exchange implementation.

```python
from mexc_sdk import MEXC

async with MEXC.new(API_KEY, API_SECRET) as sdk:
  market = await sdk.spot("BTC", "USDT")
  await strategy(market)
```

## Wallet and Earn Examples

```python
from mexc_sdk import MEXC

async with MEXC.new(API_KEY, API_SECRET) as sdk:
  deposit_methods = await sdk.wallet.deposit_methods(assets=["USDT"])
  withdrawal_methods = await sdk.wallet.withdrawal_methods(assets=["USDT"], networks=["TRC20"])
  instruments = await sdk.earn.instruments()
```

## Interfaces

Brief overview of the core interfaces:

- [`Market`](docs/market.md): unified market data and trading.
- [`Earn`](docs/earn.md): investment products (flexible/fixed/etc.) data.
- [`Wallet`](docs/wallet.md): deposit and withdrawal methods with network, fee, and confirmation data.

> [Support matrix](docs/support.md).

## Exchange Packages

Each implementation is a separate package under `impl/<exchange>/`:

- [mexc](impl/mexc/README.md)
- [binance](impl/binance/README.md)
- [bitget](impl/bitget/README.md)
- [bybit](impl/bybit/README.md)
- [bingx](impl/bingx/README.md)
- [kraken](impl/kraken/README.md)
- [dydx](impl/dydx/README.md)
- [hyperliquid](impl/hyperliquid/README.md)
- [ethereum](impl/ethereum/README.md)
