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

Extras select which venue packages get installed. See the [support matrix](https://tribulnation.com/sdk/docs/support) for what's actually implemented per venue.

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

You can read more about Market IDs and methods in the [Market](docs/market/index.md) section.

## Documentation

- [Market](docs/market/index.md) — order books, rules, orders, positions, funding
- [Earn](docs/earn/index.md) — yield-bearing instruments across venues
- [Wallet](docs/wallet/index.md) — deposit/withdrawal methods
- [Report](docs/report/index.md) — balance/position history, with provenance
- [Async Usage](docs/reference/async-usage.md) — one-shot calls and `async with`
- [Error Handling](docs/reference/error-handling.md) — the `Error` hierarchy, shared across venues
- [Context, Logging & Retries](docs/reference/context.md) — opt-in logging and retries
- [Support matrix](https://tribulnation.com/sdk/docs/support) — what's wired, per venue and per surface

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repository layout, commands, and release flow.

## License

[MIT](LICENSE)
