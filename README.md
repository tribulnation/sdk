# Tribulnation SDK

[![PyPI](https://img.shields.io/pypi/v/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> One interface, every venue. Async, fully typed, decimal-precision Python for crypto trading and data.

## Why the SDK?

- **🎯 Swap venues by changing a string**: `Market`, `Wallet`, `Earn` and `Report` are abstract interfaces, so code written against them runs unchanged on every implemented venue, and on several accounts per venue side by side.
- **🛡️ Validated at the edge**: every implementation sits on our [Typed](https://tribulnation.com/typed) clients, so venue responses are typed and validated before they reach you.
- **🔢 No raw primitives**: prices, sizes and fees are `Decimal`, timestamps are `datetime`, never `float` or epoch ints.
- **📊 Beyond trading**: `Report` reads balance and position history from exchanges *and* chains, `Earn` covers yield instruments, `Wallet` covers deposits and withdrawals.

## Installation

```bash
pip install tribulnation-sdk[dydx,hyperliquid,mexc]
```

Extras select which venue packages get installed. See the [support matrix](docs/support.md) for what's actually implemented per venue.

## Quick Start

**1. Define accounts** in `sdk.toml`:

```toml
[accounts.mexc_account1]
venue = "mexc"
api_key = "$MEXC_API_KEY"
api_secret = "$MEXC_API_SECRET"
```

`$VAR` values resolve from the environment, and a missing one fails at load time rather than on first use. Public venues (`dydx`, `hyperliquid`, `mexc`) work without an entry.

**2. Trade**:

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK.load('sdk.toml')
async with sdk.trades_stream('mexc_account1:spot:BTCUSDT') as my_trades:
  async for my_trade in my_trades:
    print(f'Hedging {my_trade}')
    await sdk.place_order('dydx:perp:BTC-USD', {
      'type': 'LIMIT', 'qty': -my_trade.qty, 'price': my_trade.price
    })
```

Or construct in code: `MarketSDK({'mexc_account1': accounts.Mexc()})`. Each `accounts.<Venue>()` field defaults to `$VENUE_FIELD`, e.g. `accounts.Mexc()` reads `$MEXC_API_KEY` and `$MEXC_API_SECRET`.

## Market IDs & Scoping

`<account_id>:<exchange_id>:<market_id>`, e.g. `mexc_account1:spot:BTCUSDT`. `account_id` is the key you registered in `accounts` (not necessarily the venue's own name), so you can run several accounts on one venue side by side. Equivalent ways to reach a market:

```python
await sdk.depth('mexc_account1:spot:BTCUSDT')

venue = await sdk.venue('mexc_account1')
await venue.depth('spot:BTCUSDT')

exchange = await venue.exchange('spot')
await exchange.depth('BTCUSDT')

market = await exchange.market('BTCUSDT')
await market.depth()
```

Hold a `Market` reference in hot loops; use the scoped one-shot calls otherwise.

## Error Handling

All errors subclass `Error`: `NetworkError`, `ValidationError`, `ApiError` (`BadRequest`, `AuthError`, `RateLimited`), `LogicError`.

## Documentation

- [Market](docs/reference/market.md) — order books, rules, orders, positions, funding
- [Earn](docs/reference/earn.md) — yield-bearing instruments across venues
- [Wallet](docs/reference/wallet.md) — deposit/withdrawal methods
- [Report](docs/reference/report.md) — balance/position history, with provenance
- [Lifecycle](docs/reference/lifecycle.md) — every SDK object is an async context manager
- [Context, Logging & Retries](docs/reference/context.md) — opt-in logging and retries
- [Support matrix](docs/support.md) — what's wired, per venue and per surface

## Development

### Repository Layout

```
docs/                # user-facing documentation
packages/
├── sdk/
│   ├── pkg/         # tribulnation-sdk
│   ├── test/        # SDK unit and regression tests
│   ├── README.md
│   └── LICENSE
├── sdk-dev/         # internal sdk-dev CLI
└── impl/            # exchange-specific implementations
    └── <venue>/
        ├── pkg/     # tribulnation-<venue>
        ├── test/    # unit tests
        ├── docs/    # venue-specific docs
        ├── README.md
        └── LICENSE
dev/
  adr/               # Architecture Decision Records
  TODO.md            # short-term task tracker
registry.toml        # implementation registry (support matrix, development stage)
```

### Commands

- Linting: `ruff check` (reads `ruff.toml`)
- Formatting: `ruff format` (reads `ruff.toml`)
- Type Checking: `pyright` (reads `pyrightconfig.json`)
- Unit Testing: `pytest`
- Integration Testing: `sdk-dev test <venue>` (reads `sdk.test.toml` for credentials to use)
- Status: `sdk-dev status` (lists all supported venues and their current development stage)
- Release: `sdk-dev release <venue>` (creates a PR on `release/<venue>` with git tag)

### CI/CD

- Deploying to PyPI: open a PR on a `release/sdk` or `release/<venue>` branch. This will create a git tag and the package will be published automatically on merge. Prefer using `sdk-dev release <venue>` to do this automatically.

## License

[MIT](LICENSE)
