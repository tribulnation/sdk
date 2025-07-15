# trading-sdk

> Abstract Crypto Trading SDK for Automated Exchange Integrations (Rust)

## Overview

`trading-sdk` provides a set of abstract traits for building automated trading systems and bots in Rust. It defines unified, type-safe protocols for trading, market data, and wallet operations, allowing you to implement these traits for any crypto exchange. This enables code reuse and rapid development of automation tools across multiple platforms.

## Features

- **Abstract Traits:** Standardized async traits for trading, market data, and wallet operations.
- **Type Safety:** Uses Rust enums and structs for robust, self-documenting code.
- **Error Handling:** Unified error types for consistent exception management.
- **Extensible:** Implement the traits for any exchange or trading platform.
- **Async-Ready:** All operations are asynchronous for high-performance automation.

## Installation

Add to your `Cargo.toml`:

```toml
[dependencies]
trading-sdk = "0.1.0"
```

## Usage

Implement the provided traits (`Trading`, `MarketData`, `Wallet`) for your target exchange:

```rust
use trading_sdk::{Trading, MarketData, Wallet};
use trading_sdk::trading::{Order, PlaceOrderResponse};
use trading_sdk::errors::AuthedError;

struct MyExchange;

#[async_trait::async_trait]
impl Trading for MyExchange {
    async fn place_order(&self, symbol: &str, order: Order) -> Result<PlaceOrderResponse, AuthedError> {
        // Implement order placement logic
        todo!()
    }
    // Implement other required methods...
}
```

See the [source code](src/) for full trait definitions and type details.

## Types & Errors

- **Order Types:** `LimitOrder`, `MarketOrder`, `Order` enum
- **Order Status:** `OrderStatus` (`New`, `PartiallyFilled`, `Filled`, `Canceled`)
- **Error Types:**
  - `NetworkFailure`, `InvalidParams`, `InvalidResponse`, `InvalidAuth`
  - `UnauthedError`, `AuthedError` enums
- **Type Aliases:**
  - `Side` (`Buy`/`Sell`)
  - `TimeInForce` (`GTC`/`IOC`/`FOK`)

## Contributing

Contributions are welcome! Please open issues or pull requests on [GitHub](https://github.com/tribulnation/sdk).

## License

MIT
