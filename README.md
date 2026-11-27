# Tribulnation SDK

[![PyPI](https://img.shields.io/pypi/v/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/tribulnation-sdk.svg)](https://pypi.org/project/tribulnation-sdk/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/tribulnation/sdk/blob/main/LICENSE)
[![Check](https://github.com/tribulnation/sdk/actions/workflows/check.yml/badge.svg)](https://github.com/tribulnation/sdk/actions/workflows/check.yml)

One async, typed Python interface for trading and market data across crypto exchanges and chains.

## Why use it

- **One interface for 20 venues.** Code written against `Market`, `Earn`, `Wallet` and `Report` runs on any venue that implements them. To switch venues, or run several accounts on one venue, you change the ID string.
- **Validated responses.** Each venue adapter is built on a [Typed](https://tribulnation.com/typed) client, so venue responses are checked before they reach your code.
- **`Decimal` and `datetime`.** Prices, sizes and fees are `Decimal`, and timestamps are timezone-aware `datetime`. No floats, no epoch integers.
- **Spot, margin and perpetual markets.** The types tell them apart: perpetuals add funding and index price, margin markets add borrow interest.
- **Reports from exchanges and chains.** `Report` reads balance and position history, `Earn` lists yield products, and `Wallet` covers deposits and withdrawals.

## Install

```bash
pip install 'tribulnation-sdk[hyperliquid]'
```

Each extra installs one venue adapter, for example `[hyperliquid,mexc,binance]`. The [support matrix](https://tribulnation.com/sdk/docs/support) shows what each venue implements.

## Quickstart

Read Hyperliquid's BTC order book and next funding rate. Public data needs no API keys:

```python
import asyncio
from tribulnation.sdk import MarketSDK, accounts

sdk = MarketSDK({'hl': accounts.Hyperliquid(public=True)})

async def main():
  book = await sdk.depth('hl::BTC')
  print('best bid:', book.best_bid)
  print('best ask:', book.best_ask)
  print(await sdk.next_funding('hl::BTC'))

asyncio.run(main())
```

```
best bid: [59976.0] 3.75746 ($225357.420960)
best ask: [59977.0] 2.10861 ($126468.101970)
NextFunding(rate=Decimal('0.0000059229'), time=datetime.datetime(2026, 11, 27, 17, 0, tzinfo=datetime.timezone(datetime.timedelta(0), 'UTC')), premium=None, interval=datetime.timedelta(seconds=3600))
```

`'hl'` is the account ID you chose, and `'hl::BTC'` is a market ID of the form `<account>:<exchange>:<market>`. An empty exchange part means Hyperliquid's default perpetuals exchange. See [Market IDs](https://tribulnation.com/sdk/docs/market/identifiers) for the format on each venue.

## Your own accounts

For trading and account data, list your accounts in a TOML file. `$VAR` values are read from the environment:

```toml
# sdk.toml
[accounts.hl]
venue = "hyperliquid"
public = true

[accounts.mexc_account1]
venue = "mexc"
api_key = "$MEXC_API_KEY"
api_secret = "$MEXC_API_SECRET"
```

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK.load('sdk.toml')
```

A missing variable fails when the file loads (`ValueError: Environment variable MEXC_API_KEY is not set`), before any request goes out. The MEXC account needs the `mexc` extra. From here, [Your First Order](https://tribulnation.com/sdk/docs/market/first-order) walks through reading rules, sizing, placing and cancelling an order.

## Documentation

- [Market](https://tribulnation.com/sdk/docs/market): order books, rules, orders, positions, funding
- [Earn](https://tribulnation.com/sdk/docs/earn): yield products across venues
- [Wallet](https://tribulnation.com/sdk/docs/wallet): deposit and withdrawal methods
- [Report](https://tribulnation.com/sdk/docs/report): balance and position history
- [Reference](https://tribulnation.com/sdk/docs/reference): async usage, errors, logging and retries
- [Support matrix](https://tribulnation.com/sdk/docs/support): what each venue implements

## Status

Beta. The core package (`tribulnation-sdk`) and each venue adapter (`tribulnation-<venue>`) have their own version numbers and are released separately. Release notes are on the [GitHub releases page](https://github.com/tribulnation/sdk/releases). Questions and bug reports go to [GitHub issues](https://github.com/tribulnation/sdk/issues).

## Contributing

See [CONTRIBUTING.md](https://github.com/tribulnation/sdk/blob/main/CONTRIBUTING.md) for the repository layout, commands and release flow. Maintainer guides and architecture decisions are in the [developer documentation](https://github.com/tribulnation/sdk/blob/main/dev-docs/README.md).

## License

[MIT](https://github.com/tribulnation/sdk/blob/main/LICENSE)
