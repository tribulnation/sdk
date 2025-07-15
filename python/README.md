# Trading SDK

> Abstract Crypto Trading SDK for Automated Exchange Integrations

## Overview

The Trading SDK provides a set of abstract interfaces for building automated trading systems and bots. It defines unified, type-safe protocols for trading, market data, and wallet operations, allowing you to implement these interfaces for any crypto exchange. This enables code reuse and rapid development of automation tools across multiple platforms.

## Features

- **Abstract Protocols:** Standardized async interfaces for trading, market data, and wallet operations.
- **Type Safety:** Uses Python type hints and TypedDicts for robust, self-documenting code.
- **Error Handling:** Unified error types for consistent exception management.
- **Extensible:** Implement the protocols for any exchange or trading platform.
- **Async-Ready:** All operations are asynchronous for high-performance automation.

## Installation

```bash
pip install trading-sdk
```

## Usage

Implement the provided protocols (`Trading`, `MarketData`, `Wallet`) for your target exchange:

```python
from trading_sdk import Trading, MarketData, Wallet

class MyExchangeTrading(Trading):
    async def place_order(self, symbol, order):
        # Implement order placement logic
        ...
    # Implement other required methods...

class MyExchangeMarketData(MarketData):
    async def order_book(self, symbol, limit=None):
        # Implement order book retrieval
        ...
    # Implement other required methods...

class MyExchangeWallet(Wallet):
    async def withdraw(self, currency, address, amount, network=None):
        # Implement withdrawal logic
        ...
    # Implement other required methods...
```

See the [source code](src/trading_sdk/) for full interface definitions and type details.

## Types & Errors

- **Order Types:** `LIMIT`, `LIMIT_MAKER`, `MARKET`
- **Order Status:** `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`
- **Error Types:** `NetworkFailure`, `InvalidParams`, `InvalidResponse`, `InvalidAuth`
- **Type Aliases:** `Side` (`BUY`/`SELL`), `TimeInForce` (`GTC`/`IOC`/`FOK`), `Num` (str/Decimal/int)

## Contributing

Contributions are welcome! Please open issues or pull requests on [GitHub](https://github.com/tribulnation/sdk.git).

## License

MIT


